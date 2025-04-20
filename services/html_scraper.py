import json
import random
import re
import shutil
import string
import aiohttp
import brotli
from selenium.webdriver.support.wait import WebDriverWait
import seleniumwire.undetected_chromedriver.v2 as uc
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from utils.logger import setup_logger
import os
from dotenv import load_dotenv
from seleniumwire import webdriver
load_dotenv()

STATE = os.getenv("STATE")
logger = setup_logger("scraper")
async def generate_random_user_agent():
    browsers = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/89.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.48',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/89.0',
    ]
    return random.choice(browsers)
async def generate_random_language():
    languages = ['en-US']
    return random.choice(languages)
async def fetch_company_details(old_url: str) -> dict:
    try:
        match = re.search(r"/business/([A-Z0-9]+)/", old_url)
        if match:
            id = match.group(1)
            url = "https://biz.sosmt.gov/search/business"
            options = webdriver.ChromeOptions()
            script_dir = os.path.dirname(os.path.realpath(__file__))
            profile = os.path.join(script_dir, "profile")
            if not os.path.exists(profile):
                os.makedirs(profile)
            else:
                shutil.rmtree(profile)
            word = ''.join(random.choices(string.ascii_letters, k=10))
            profile_path = os.path.join(profile, word)
            options.add_argument(f"--user-data-dir={profile_path}")
            options.add_argument(f'--user-agent={await generate_random_user_agent()}')
            options.add_argument(f'--lang={await generate_random_language()}')
            options.add_argument("--headless=new")
            options.add_argument("--start-maximized")
            options.add_argument("--disable-webrtc")
            options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
            options.add_argument("--force-webrtc-ip-handling-policy=default_public_interface_only")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-features=DnsOverHttps")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-blink-features=AutomationControlled")
            driver = uc.Chrome(options=options)

            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                            const getContext = HTMLCanvasElement.prototype.getContext;
                            HTMLCanvasElement.prototype.getContext = function(type, attrs) {
                                const ctx = getContext.apply(this, arguments);
                                if (type === '2d') {
                                    const originalToDataURL = this.toDataURL;
                                    this.toDataURL = function() {
                                        return "data:image/png;base64,fake_canvas_fingerprint";
                                    };
                                }
                                return ctx;
                            };
                            """
            })
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                        Object.defineProperty(navigator, 'webdriver', {
                          get: () => undefined
                        })
                      '''
            })
            driver.get(url)
            input_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                                                "#root > div > div.content > div > main > div.search-box > div.search-input-wrapper > div.inner-input-wrapper > form > input"))
            )
            input_field.send_keys(id)
            button = driver.find_element(By.CSS_SELECTOR,
                                         "#root > div > div.content > div > main > div.search-box > div.search-input-wrapper > button")
            button.click()
            wait = WebDriverWait(driver, 10)  # Ожидаем до 10 секунд
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#root > div > div.content > div > main > div.table-wrapper > table")))
            for x in driver.requests:
                if x.host == "biz.sosmt.gov" and x.method == "POST" and x.path == "/api/Records/businesssearch":
                    byte_str = x.response.body
                    decoded_content = brotli.decompress(byte_str)
                    decoded_string = decoded_content.decode('utf-8', errors='ignore')
                    json_data = json.loads(decoded_string)
            row_1 = driver.find_element(By.CSS_SELECTOR,
                                         '#root > div > div.content > div > main > div.table-wrapper > table > tbody > tr:nth-child(1) > td:nth-child(1) > div')
            row_1.click()
            wait.until(EC.visibility_of_element_located((
                By.CSS_SELECTOR,
                "#root > div > div.content > div > main > div.drawer.show > div > div.scrollable-drawer-wrapper > div > div > table > tbody"
            )))
            json_data_details = {}
            for x in driver.requests:
                if x.host == "biz.sosmt.gov" and x.method == "GET" and "api/FilingDetail/business" in x.path:
                    try:
                        byte_str = x.response.body
                        decoded_content = brotli.decompress(byte_str)
                        decoded_string = decoded_content.decode('utf-8', errors='ignore')
                        json_data_details = json.loads(decoded_string)
                    except Exception as e:
                        continue
            driver.quit()
            result = await parse_html_name_agent(json_data)
            record_num, id, name, agent = result["record_num"], result["id"], result["name"], result["agent"]
        else:
            logger.error(f"Error fetching data for query '{old_url}'")
            return []
        return await parse_html_details(json_data_details, record_num, id, name, agent)
    except Exception as e:
        driver.quit()
        logger.error(f"Error fetching data for query '{url}': {e}")
        return []
async def fetch_company_data(query: str) -> list[dict]:
    try:
        url = "https://biz.sosmt.gov/search/business"
        options = webdriver.ChromeOptions()
        script_dir = os.path.dirname(os.path.realpath(__file__))
        profile = os.path.join(script_dir, "profile")
        if not os.path.exists(profile):
            os.makedirs(profile)
        else:
            shutil.rmtree(profile)
        word = ''.join(random.choices(string.ascii_letters, k=10))
        profile_path = os.path.join(profile, word)
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument(f'--user-agent={await generate_random_user_agent()}')
        options.add_argument(f'--lang={await generate_random_language()}')
        options.add_argument("--headless=new")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-webrtc")
        options.add_argument("--disable-features=WebRtcHideLocalIpsWithMdns")
        options.add_argument("--force-webrtc-ip-handling-policy=default_public_interface_only")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-features=DnsOverHttps")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-blink-features=AutomationControlled")
        driver = uc.Chrome(options=options)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                const getContext = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(type, attrs) {
                    const ctx = getContext.apply(this, arguments);
                    if (type === '2d') {
                        const originalToDataURL = this.toDataURL;
                        this.toDataURL = function() {
                            return "data:image/png;base64,fake_canvas_fingerprint";
                        };
                    }
                    return ctx;
                };
                """
        })
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
          '''
        })
        driver.get(url)
        input_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                                            "#root > div > div.content > div > main > div.search-box > div.search-input-wrapper > div.inner-input-wrapper > form > input"))
        )
        input_field.send_keys(query)
        button = driver.find_element(By.CSS_SELECTOR,
                                     "#root > div > div.content > div > main > div.search-box > div.search-input-wrapper > button")
        button.click()
        wait = WebDriverWait(driver, 10)  # Ожидаем до 10 секунд
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#root > div > div.content > div > main > div.table-wrapper > table")))
        for x in driver.requests:
            if x.host == "biz.sosmt.gov" and x.method == "POST" and x.path == "/api/Records/businesssearch":
                byte_str = x.response.body
                decoded_content = brotli.decompress(byte_str)
                decoded_string = decoded_content.decode('utf-8', errors='ignore')
                json_data = json.loads(decoded_string)
        driver.quit()
        return await parse_html_search(json_data)
    except Exception as e:
        logger.error(f"Error fetching data for query '{query}': {e}")
        return []

async def parse_html_search(data: dict) -> list[dict]:
    results = []
    for entity_id, data_row in data["rows"].items():
        entity_name = data_row.get("TITLE", [""])[0]  # берём первую строку из TITLE
        status = data_row.get("STATUS", "")
        id = data_row.get("RECORD_NUM", "").lstrip("0")
        results.append({
                "state": STATE,
                "name": entity_name,
                "status": status,
                "id": entity_id,
                "url": f"https://biz.sosmt.gov/api/FilingDetail/business/{id}/false"
            })
    return results

async def parse_html_name_agent(data: dict) -> dict:
    for entity_id, data_row in data["rows"].items():
        entity_name = data_row.get("TITLE", [""])[0]  # берём первую строку из TITLE
        agent = data_row.get("AGENT", "")
        record_num = data_row.get("RECORD_NUM", "")
        return {
            "record_num": record_num,
            "id": entity_id,
            "name": entity_name,
            "agent": agent
        }


async def parse_html_details(data: dict, record_num: str, id: str, name: str, agent: str) -> dict:
    async def fetch_documents(record_num: str) -> list[dict]:
        url = f"https://biz.sosmt.gov/api/History/business/{record_num}"
        headers = {
            'Content-Type': 'application/json'
        }
        results = []
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = json.loads(await response.text())
                    base_url = "https://biz.sosmt.gov"
                    for amendment in data["AMENDMENT_LIST"]:
                        try:
                            download_link = base_url + amendment["DOWNLOAD_LINK"]
                            file_name = amendment["AMENDMENT_TYPE"]
                            file_date = amendment["AMENDMENT_DATE"]
                            results.append({
                                "name": file_name,
                                "date": file_date,
                                "link": download_link,
                            })
                        except Exception as e:
                            continue
                    return results
        except Exception as e:
            logger.error(f"Error fetching data for record_num '{record_num}': {e}")
            return []


    detail_map = {item["LABEL"]: item["VALUE"] for item in data.get("DRAWER_DETAIL_LIST", [])}
    mailing_address = detail_map.get("Mailing Address") or ""
    principal_address = detail_map.get("Principal Address") or ""
    document_images = await fetch_documents(record_num)
    status = detail_map.get("Status")
    date_registered = detail_map.get("Registration Date")
    entity_type = detail_map.get("Filing Type")
    return {
        "state": STATE,
        "name": name,
        "status": status.strip() if status else None,
        "registration_number": record_num,
        "date_registered": date_registered.strip() if date_registered else None,
        "entity_type": entity_type.strip() if entity_type else None,
        "agent_name": agent,
        "principal_address": principal_address.strip() if principal_address else None,
        "mailing_address": mailing_address.strip() if mailing_address else None,
        "document_images": document_images
    }