# 📚 KOTO WEB UI - PLAYWRIGHT E2E TESTING DOCUMENTATION INDEX

## 📖 Documentation Files Created

This exploration has generated comprehensive documentation for writing Playwright E2E tests for the Koto UI.

### 1. **E2E_EXPLORATION_SUMMARY.md** ⭐ START HERE
   - **Purpose**: High-level overview of UI structure and key findings
   - **Contents**:
     - Project layout
     - Theme toggle mechanism
     - Settings button & panel
     - Model selector details
     - Notification system
     - Sidebar navigation
     - Modal containers
     - Keyboard shortcuts
     - API endpoints
     - Global state variables
     - Recommended test structure
     - Testing checklist

### 2. **PLAYWRIGHT_QUICK_REFERENCE.md** 🚀 FOR QUICK LOOKUPS
   - **Purpose**: Quick copy-paste selectors and test patterns
   - **Contents**:
     - Most used selectors
     - Chat interface selectors
     - Header buttons
     - Theme values
     - Common test template
     - State checking code
     - Full workflow example
     - HTML structure overview
     - Key IDs and classes

### 3. **PLAYWRIGHT_E2E_GUIDE.md** 📋 COMPREHENSIVE GUIDE
   - **Purpose**: Detailed reference for all UI elements
   - **Contents**:
     - Navigation/header elements
     - Theme selector system (8 themes)
     - Settings panel controls (15+ controls)
     - Chat interface elements
     - Sidebar and panels
     - Modals and dialogs (12+ types)
     - CSS classes for styling
     - Keyboard shortcuts with details
     - Theme activation and detection
     - Settings API endpoint structure
     - State management variables
     - Common Playwright patterns
     - URL routes
     - Asset locations
     - Testing tips
     - Debug helpers

### 4. **PLAYWRIGHT_HTML_SNIPPETS.md** 💻 ACTUAL CODE REFERENCES
   - **Purpose**: Real HTML code and test examples
   - **Contents**:
     - Actual HTML for theme selector (with all 8 themes)
     - Settings button HTML
     - Notification button implementation
     - Model selector dropdown
     - Chat input form (file, voice, message, send)
     - Mini game panel structure
     - Full settings panel structure
     - Sidebar HTML
     - JavaScript event handlers (theme, settings, keyboard)
     - Complete settings JSON response
     - Test code examples for each section

---

## 🎯 QUICK START FOR E2E TESTING

### Step 1: Understand the Structure
Read: **E2E_EXPLORATION_SUMMARY.md** (5-10 min)

### Step 2: Get Element Selectors
Read: **PLAYWRIGHT_QUICK_REFERENCE.md** or **PLAYWRIGHT_E2E_GUIDE.md** (lookup as needed)

### Step 3: See Actual Code
Read: **PLAYWRIGHT_HTML_SNIPPETS.md** to understand the exact HTML structure

### Step 4: Write Your Tests
Use the test examples provided in each document

---

## 🎯 KEY SELECTORS YOU'LL USE MOST

### Theme Toggle
\\\
.theme-option[data-theme="dark"]
.theme-option[data-theme="light"]
.theme-option[data-theme="ocean"]
(... 5 more themes)
\\\

### Settings
\\\
button[title="设置"]           # Settings button
#settingsPanel                 # Settings panel
#themeSelector                 # Theme container
#settingModel                  # Model dropdown
#settingShowThinking           # Thinking checkbox
\\\

### Chat
\\\
#messageInput                  # Message textarea
#sendBtn                       # Send button
#chatMessages                  # Chat history
#voiceBtn                      # Voice input
#fileInput                     # File upload
\\\

### Navigation
\\\
.nav-rail.chatgpt-sidebar     # Sidebar
#sessionsList                  # Sessions
#navSkillsBtn                  # Skills panel
#statusIndicator              # Server status
\\\

---

## ⌨️ KEYBOARD SHORTCUTS TO TEST

| Keys | Action | Selector |
|------|--------|----------|
| Ctrl+K | New chat | #newSessionModal |
| Escape | Stop AI | (when generating) |
| Enter | Send message | #messageInput + #sendBtn |

---

## �� EXAMPLE TEST STRUCTURE

`javascript
import { test, expect } from '@playwright/test';

test.describe('Koto Theme System', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');
  });

  test('Change theme from dark to light', async ({ page }) => {
    // 1. Open settings
    await page.click('button[title="设置"]');
    await page.waitForSelector('#settingsPanel.active');
    
    // 2. Select light theme
    await page.click('.theme-option[data-theme="light"]');
    
    // 3. Verify theme changed
    const theme = await page.evaluate(() => 
      document.documentElement.getAttribute('data-theme')
    );
    expect(theme).toBe('light');
    
    // 4. Close settings
    await page.click('button[onclick="closeSettings()"]');
  });

  test('All themes are clickable', async ({ page }) => {
    const themes = ['dark', 'light', 'ocean', 'forest', 'sunset', 'lavender', 'midnight', 'auto'];
    
    await page.click('button[title="设置"]');
    await page.waitForSelector('#settingsPanel.active');
    
    for (const theme of themes) {
      await page.click(\.theme-option[data-theme="\"]\);
      
      const current = await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme')
      );
      expect(current).toBe(theme);
    }
  });
});
`

---

## 📊 HTML FILES ANALYZED

| File | Size | Purpose |
|------|------|---------|
| web/templates/index.html | 179 KB | **Main UI** - All elements here |
| web/static/js/app.js | Large | App logic, event handlers, state |
| web/static/css/style.css | Large | Theme colors, layout, variables |
| web/static/js/app-framework.js | - | Framework utilities |
| web/static/js/auth.js | - | Authentication |

---

## �� HOW TO FIND ELEMENTS

### Method 1: Use Browser DevTools
1. Open Koto UI
2. Press F12
3. Press Ctrl+Shift+C (Select element)
4. Click on element you want to test
5. Note the ID or class in DevTools

### Method 2: Search Documentation
1. Open PLAYWRIGHT_QUICK_REFERENCE.md
2. Ctrl+F to search for element name
3. Copy the selector
4. Use in your test

### Method 3: Check HTML File
1. View web/templates/index.html
2. Search for the element
3. Copy the ID or class

### Method 4: Check Snippets
1. View PLAYWRIGHT_HTML_SNIPPETS.md
2. Find the section with your element
3. See exact HTML and test example

---

## 📋 ELEMENT CATEGORIES

### 🎨 Appearance Elements
- Theme selector (8 options)
- UI zoom slider
- Font size buttons

### ⚙️ Settings Elements
- Model selector
- Checkboxes (show thinking, auto-save, etc.)
- Directory inputs
- Proxy settings

### 💬 Chat Elements
- Message input textarea
- Send button
- File upload
- Voice input
- Chat history

### 🗂️ Navigation Elements
- Sidebar
- Sessions list
- Skills button
- Status indicator

### 📦 Panels & Modals
- Settings panel
- Workspace panel
- Skills panel
- Notification center
- Voice panel
- Suggestion panel
- Mini game panel

---

## 🚀 RECOMMENDED TESTING ORDER

1. **Basic Navigation**
   - Click settings button
   - Open various panels
   - Click navigation items

2. **Theme System**
   - Switch between all 8 themes
   - Verify theme persists
   - Check CSS variables updated

3. **Settings Panel**
   - Test model selection
   - Toggle each checkbox
   - Modify directory paths
   - Zoom UI to different sizes

4. **Chat Functionality**
   - Type and send messages
   - Upload files
   - Test voice button visibility

5. **Keyboard Shortcuts**
   - Ctrl+K for new session
   - Enter to send message
   - Escape to close modals

6. **Advanced**
   - Skills management
   - Shadow watcher
   - Token monitoring
   - Notifications

---

## ✅ VALIDATION CHECKLIST

Before running your tests, verify:

- [ ] Koto server is running (check http://localhost:3000)
- [ ] Browser is compatible (Chrome, Firefox, Edge)
- [ ] Playwright is installed (npm install -D @playwright/test)
- [ ] Test files are in correct directory (tests/ or e2e/)
- [ ] Selectors match actual UI (run manually first)
- [ ] Wait times are reasonable (5-10 seconds max)
- [ ] Tests can run headless (headless: true)
- [ ] Screenshots capture properly
- [ ] Reports generate correctly

---

## 🐛 TROUBLESHOOTING

### Element Not Found
1. Check selector in DevTools
2. Wait longer: \wait page.waitForSelector(..., { timeout: 10000 })\
3. Check if element is inside iframe (it's not in this case)
4. Try alternative selectors

### Theme Not Applied
1. Check if element has class "active"
2. Use \waitForLoadState('networkidle')\ after theme change
3. Verify CSS variables are updated
4. Check if localStorage is interfering

### Settings Panel Won't Open
1. Verify button selector is correct
2. Check for modal overlay blocking it
3. Wait for panel to be visible: \waitForSelector(..., { visible: true })\
4. Try clicking again with delay

### Keyboard Shortcuts Not Working
1. Verify focus is on correct element
2. Check if modal is open (shortcuts disabled)
3. Use platform-specific keys (Ctrl vs Cmd)
4. Test in browser console first

---

## 📞 SUPPORT REFERENCES

### Files in Repository
- Templates: \web/templates/\
- JavaScript: \web/static/js/\
- CSS: \web/static/css/\
- Static assets: \web/static/assets/\

### API Endpoints
- \GET /api/settings\ - Fetch settings
- \POST /api/settings\ - Update settings
- \POST /api/settings/reset\ - Reset to defaults

### Global Functions (in browser console)
- \selectTheme(theme)\ - Change theme
- \openSettings()\ - Open settings
- \closeSettings()\ - Close settings
- \isSessionGenerating(session)\ - Check if generating

---

## 📝 DOCUMENTATION SUMMARY

| Document | When to Use | Contents |
|----------|-------------|----------|
| **E2E_EXPLORATION_SUMMARY.md** | Overview & quick reference | High-level structure, key findings |
| **PLAYWRIGHT_QUICK_REFERENCE.md** | Copy-paste selectors | Selectors, test templates, shortcuts |
| **PLAYWRIGHT_E2E_GUIDE.md** | Detailed reference | Complete element list, classes, patterns |
| **PLAYWRIGHT_HTML_SNIPPETS.md** | Understanding HTML | Actual code, test examples, JSON |

---

## 🎓 LEARNING PATH

1. **New to Koto UI?** → Start with **E2E_EXPLORATION_SUMMARY.md**
2. **Need a selector?** → Check **PLAYWRIGHT_QUICK_REFERENCE.md**
3. **Writing a test?** → Reference **PLAYWRIGHT_E2E_GUIDE.md**
4. **Confused about HTML?** → Look at **PLAYWRIGHT_HTML_SNIPPETS.md**
5. **Writing complex test?** → Combine all documents

---

## 🏁 NEXT STEPS

1. Read the **E2E_EXPLORATION_SUMMARY.md** (starts with most important info)
2. Choose your test scenario (theme switching, settings, chat, etc.)
3. Find selectors in **PLAYWRIGHT_QUICK_REFERENCE.md**
4. Copy test template from **PLAYWRIGHT_HTML_SNIPPETS.md**
5. Modify and run your test
6. Debug using provided troubleshooting tips

---

**Generated**: 2026-03-17
**Files Created**: 4 markdown documents
**Selectors Found**: 50+ unique element selectors
**Test Templates**: 15+ example tests
**Themes Documented**: 8 theme options
**Settings Items**: 15+ settings elements

Good luck with your Playwright E2E tests! 🚀

