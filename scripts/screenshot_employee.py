import asyncio
from playwright.async_api import async_playwright
import os

SCREENSHOTS_DIR = r"e:\CAPSTONE PROJECT\PowerWize\static\screenshots"
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

BASE_URL = "http://127.0.0.1:5000"
EMAIL    = "roberto.delacruz@ewize.com"
PASSWORD = "Test@1234"

async def shot(page, name, wait_ms=1200):
    await page.wait_for_timeout(wait_ms)
    path = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=True)
    print(f"  [{name}]")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        # ── 1. Login ─────────────────────────────────────────────────────────
        await page.goto(f"{BASE_URL}/auth")
        await page.fill('input[name="email"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await shot(page, "01_login")
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/employee**", timeout=8000)
        await shot(page, "02_dashboard")

        # ── 2. Training Modules list ──────────────────────────────────────────
        await page.click('.nav-item:has-text("Training Modules")')
        await shot(page, "03_modules_list")

        # ── 3. Archive the first active module ───────────────────────────────
        # Auto-accept any confirm dialogs
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        # Submit the archive form directly (bypass the confirm button)
        archive_form = page.locator('form[action*="/archive"]').first
        await archive_form.evaluate("f => f.submit()")
        await page.wait_for_url("**/employee**", timeout=6000)
        await page.click('.nav-item:has-text("Training Modules")')
        await shot(page, "04_modules_with_archived_section")

        # ── 4. Create a fresh module ──────────────────────────────────────────
        await page.goto(f"{BASE_URL}/lms/modules/create")
        await shot(page, "05_create_module_empty")
        await page.fill('input[name="title"]', "Solar Safety & Grid Connection")
        await page.fill('textarea[name="description"]', "Covers electrical safety protocols, grid-tie standards, and connection procedures for solar PV systems.")
        await page.select_option('select[name="training_type"]', "training")
        await shot(page, "06_create_module_filled")
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(2000)

        # Get the module ID from the current URL (redirects to manage page)
        current_url = page.url
        module_id = current_url.rstrip("/").split("/")[-1]
        if not module_id.isdigit():
            # fallback: go to modules list and get first manage link
            await page.goto(f"{BASE_URL}/employee")
            await page.click('.nav-item:has-text("Training Modules")')
            href = await page.locator('a.mod-btn[href*="/lms/modules/"]').first.get_attribute("href")
            module_id = href.split("/")[-1]

        await shot(page, "07_manage_module_after_create")

        # ── 5. Add Quiz ───────────────────────────────────────────────────────
        await page.goto(f"{BASE_URL}/lms/modules/{module_id}/quiz")
        await shot(page, "08_quiz_page_empty")

        # Save quiz meta
        await page.fill('input[name="title"]', "Solar Safety Quiz")
        await page.fill('input[name="time_limit"]', "30")
        await page.fill('input[name="passing_score"]', "75")
        try:
            await page.fill('textarea[name="description"]', "Test your knowledge of solar PV safety and grid connection standards.")
        except:
            pass
        await shot(page, "09_quiz_meta_filled")
        # Submit save_meta
        await page.evaluate("""
            const f = document.querySelector('form');
            const inp = document.createElement('input');
            inp.type = 'hidden'; inp.name = 'action'; inp.value = 'save_meta';
            f.appendChild(inp); f.submit();
        """)
        await page.wait_for_url(f"**/modules/{module_id}/quiz**", timeout=6000)
        await shot(page, "10_quiz_after_meta_saved")

        # ── 6. Add Exam ───────────────────────────────────────────────────────
        await page.goto(f"{BASE_URL}/lms/modules/{module_id}/exam")
        await shot(page, "11_exam_page_empty")

        # Fill exam meta
        await page.fill('input[name="title"]', "Solar Grid Connection Practical Exam")
        try:
            await page.fill('textarea[name="instructions"]', "Install a simulated grid-tie solar PV system following all safety protocols. You will be assessed on proper wiring, grounding, and documentation.")
        except:
            pass
        try:
            await page.fill('textarea[name="criteria"]', "1. Proper PPE usage\n2. Correct wiring connections\n3. Safety grounding\n4. System documentation")
        except:
            pass
        await shot(page, "12_exam_meta_filled")
        # Submit save_meta
        await page.evaluate("""
            const f = document.querySelector('form');
            const inp = document.createElement('input');
            inp.type = 'hidden'; inp.name = 'action'; inp.value = 'save_meta';
            f.appendChild(inp); f.submit();
        """)
        await page.wait_for_url(f"**/modules/{module_id}/exam**", timeout=6000)
        await shot(page, "13_exam_after_meta_saved")

        # ── 7. Back to manage page showing quiz + exam ────────────────────────
        await page.goto(f"{BASE_URL}/lms/modules/{module_id}")
        await shot(page, "14_manage_module_complete")

        await browser.close()
        print(f"\nDone. Screenshots saved to: {SCREENSHOTS_DIR}")

asyncio.run(main())
