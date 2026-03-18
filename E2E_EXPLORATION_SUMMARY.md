# KOTO UI EXPLORATION - SUMMARY FOR E2E TESTING

## 📁 Project Layout

### Templates
- **Main**: `web/templates/index.html` (179 KB - all UI)
- Others: `landing.html`, `mobile.html`, `mini_koto.html`, etc.

### JavaScript
- **app.js** - Main app logic, state management, event handlers
- **app-framework.js** - Framework utilities
- **skill_marketplace.js** - Skills marketplace features
- **auth.js** - Authentication

### Stylesheets  
- **style.css** - Main theme and layout styles (uses CSS variables)
- **skill_marketplace.css** - Skill-specific styles

---

## 🎯 KEY FINDINGS FOR E2E TESTING

### 1️⃣ THEME TOGGLE (Dark/Light Mode)

**HTML Structure**:
- 8 theme options in settings panel
- Each theme is a `.theme-option[data-theme="X"]` div

**Available Themes**:
- dark, light, ocean, forest, sunset, lavender, midnight, auto

**How to Test**:
\\\javascript
// Click settings
await page.click('button[title="设置"]');

// Select theme
await page.click('.theme-option[data-theme="dark"]');

// Verify
const theme = await page.evaluate(() => 
  document.documentElement.getAttribute('data-theme')
);
expect(theme).toBe('dark');
\\\

**Key IDs**:
- `#themeSelector` - Container
- `#settingsPanel` - Settings sidebar (opens when clicked)
- CSS Variables: `--bg-primary`, `--text-primary`, etc.

---

### 2️⃣ SETTINGS BUTTON/GEAR ICON

**Selector**: `button[title="设置"]` (most reliable)
**Alternative**: `button[onclick="openSettings()"]`
**Panel ID**: `#settingsPanel`
**Close Button**: `button[onclick="closeSettings()"]`

**Panel Content**:
- Model selector (`#settingModel`)
- AI toggles (show thinking, show task type, auto-save files, etc.)
- Theme selector
- UI zoom slider (`#uiZoomSlider`)
- Proxy settings
- Directory settings
- Storage paths

**Test Pattern**:
\\\javascript
await page.click('button[title="设置"]');
await page.waitForSelector('#settingsPanel.active');
// ... make changes ...
await page.click('button[onclick="closeSettings()"]');
\\\

---

### 3️⃣ MODEL SELECTOR/DROPDOWN

**ID**: `#settingModel`
**Type**: `<select>` element
**Available Models**:
- auto (Smart selection)
- gemini-3-flash-preview (Fast)
- gemini-3-pro-preview (Smart)
- gemini-3.1-flash-image-preview (Image)
- gemini-2.5-flash
- gemini-2.5-pro

**Test**:
\\\javascript
await page.selectOption('#settingModel', 'gemini-3-pro-preview');
\\\

---

### 4️⃣ NOTIFICATION/REMINDERS BUTTON

**Selector**: `button.notification-btn`
**Badge ID**: `#notificationBadge` (shows count)
**Modal ID**: `#notificationPanelModal`
**Label**: "🔔 通知" (Notification)

**Found In**: Top header, right of token monitor

**Test**:
\\\javascript
await page.click('button.notification-btn');
await page.waitForSelector('#notificationPanelModal', { visible: true });
\\\

---

### 5️⃣ SIDEBAR NAVIGATION

**Selector**: `.nav-rail.chatgpt-sidebar`
**Main Items**:
- Logo/Home: `.logo.redesigned-logo`
- New Session: `button[onclick="showNewSessionModal()"]`
- Sessions List: `#sessionsList`
- Skills: `#navSkillsBtn`
- Status: `#statusIndicator`
- Jobs: `#jobsRunningPill`

**Can be resized**: `#sidebarResizeHandle` (drag to resize)

---

### 6️⃣ MODAL/PANEL CONTAINERS

| Modal ID | Purpose | Class |
|----------|---------|-------|
| `#settingsPanel` | Settings sidebar | Aside |
| `#workspacePanel` | File browser | Aside |
| `#skillsPanel` | Skills management | Aside |
| `#newSessionModal` | Create new chat | Modal |
| `#voicePanelModal` | Voice input | Modal |
| `#notificationPanelModal` | Notifications | Modal |
| `#suggestionPanelModal` | AI suggestions | Modal |
| `#triggerPanelModal` | Scheduled tasks | Modal |
| `#setupWizard` | Initial setup | Modal |
| `#miniGamePanel` | Dino game | Div (hidden) |

**Detection**:
- Active modal: `.modal-overlay.active`
- Panels open with `.active` class

---

## ⌨️ KEYBOARD SHORTCUTS

### Global Handlers
- **Location**: `handleGlobalKeyDown(e)` function in app.js
- **Registered**: `window.addEventListener('keydown', handleGlobalKeyDown)`

**Shortcuts**:
| Keys | Action |
|------|--------|
| Ctrl+K / Cmd+K | New session modal |
| Escape (when generating) | Stop message generation |
| Enter | Send message |
| Shift+Enter | Newline in input |
| Escape | Close modals |

**Test Pattern**:
\\\javascript
await page.keyboard.press('Control+K');  // or Meta+K for Mac
await page.waitForSelector('#newSessionModal');
\\\

---

## 🔍 CSS CLASSES FOR SELECTORS

**Common Classes**:
- `.ghost-btn` - Transparent buttons
- `.btn-primary` - Primary action button
- `.btn-secondary` - Secondary button
- `.toggle` - Toggle switch
- `.toggle-slider` - Animated toggle
- `.modal` - Modal dialog
- `.modal-overlay` - Modal backdrop
- `.active` - Active/selected state
- `.hidden` - Hidden (display: none)
- `.theme-option` - Theme selector option
- `.theme-preview` - Preview within theme option

---

## 🔌 API ENDPOINTS

### Settings
- **GET/POST** `/api/settings`
- **Structure**: appearance, ai, storage, proxy

### Reset
- **POST** `/api/settings/reset`

### Skills
- **GET** `/api/skills`
- **POST** `/api/skills/{{id}}/toggle`

---

## 🧠 GLOBAL STATE VARIABLES (in browser console)

\\\javascript
currentSession       // Current chat session object
selectedModel        // Selected AI model name
currentSettings      // All settings object
enableMiniGame       // Mini-game flag
selectedFiles        // Attached files array
\\\

**Helper Functions**:
\\\javascript
isSessionGenerating(currentSession)   // Check if AI is responding
selectTheme(theme)                    // Change theme
openSettings()                        // Open settings panel
loadSettings()                        // Fetch settings from server
applyTheme(theme)                     // Apply theme immediately
\\\

---

## 📊 CHAT INTERFACE ELEMENTS

| Element | ID/Selector | Type | Purpose |
|---------|-------------|------|---------|
| Chat history | `#chatMessages` | Div | All messages display here |
| Message input | `#messageInput` | Textarea | User types here |
| Send button | `#sendBtn` | Button | Submit message |
| Voice button | `#voiceBtn` | Button | Start voice recording |
| File upload | `#fileInput` | Input[file] | Attach documents |
| File preview | `#filePreview` | Div | Shows attached files |
| Mini game | `#miniGamePanel` | Div | Dino game (initially hidden) |
| Mini game canvas | `#miniGameCanvas` | Canvas | Game rendering |
| Welcome screen | `#welcomeScreen` | Div | Initial empty state |

**Test Pattern - Send Message**:
\\\javascript
await page.fill('#messageInput', 'Hello Koto');
await page.press('#messageInput', 'Enter');
await page.waitForTimeout(1000);  // Wait for response
\\\

---

## 🎨 THEME SYSTEM DETAILS

### How Themes Work
1. Click theme option (e.g., `.theme-option[data-theme="dark"]`)
2. Calls `selectTheme('dark')`
3. Sets `data-theme` attribute on `<html>`
4. CSS variables update based on theme
5. All components react to new colors

### Current Theme Detection
\\\javascript
// In tests:
const theme = await page.evaluate(() =>
  document.documentElement.getAttribute('data-theme')
);
\\\

### Available Themes
- **dark** - Dark background, light text
- **light** - Light background, dark text
- **ocean** - Blue theme
- **forest** - Green theme
- **sunset** - Orange/pink theme
- **lavender** - Purple theme
- **midnight** - Deep blue theme
- **auto** - Follow system preference

---

## 🚀 RECOMMENDED TEST STRUCTURE

\\\javascript
import { test, expect } from '@playwright/test';

test.describe('Koto UI Settings', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');
  });
  
  test('Theme switching', async ({ page }) => {
    // Test each theme
    for (const theme of ['dark', 'light', 'ocean', 'forest']) {
      await page.click('button[title="设置"]');
      await page.click(\.theme-option[data-theme="\"]\);
      
      const currentTheme = await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme')
      );
      expect(currentTheme).toBe(theme);
    }
  });
  
  test('Model selection', async ({ page }) => {
    await page.click('button[title="设置"]');
    await page.selectOption('#settingModel', 'gemini-3-pro-preview');
    
    const value = await page.inputValue('#settingModel');
    expect(value).toBe('gemini-3-pro-preview');
  });
  
  test('Keyboard shortcuts', async ({ page }) => {
    await page.keyboard.press('Control+K');
    await page.waitForSelector('#newSessionModal');
    const isVisible = await page.locator('#newSessionModal').isVisible();
    expect(isVisible).toBe(true);
  });
});
\\\

---

## 📝 HTML FILES ANALYSIS

**Main Template** (`index.html`):
- Contains all UI in single file (~179 KB)
- Uses Jinja2 templating (`{{ url_for() }}`)
- 8 theme options in settings section
- All major panels defined (settings, workspace, skills, artifacts)
- Multiple modals for different functions

**Other Templates**:
- `landing.html` - Landing/welcome page
- `mobile.html` - Mobile optimized
- `mini_koto.html` - Compact mode
- `notebook_lm.html` - Notebook interface
- `edit_ppt.html` - PowerPoint editor
- Others for specific features

---

## ✅ TESTING CHECKLIST

- [ ] Theme switching (all 8 themes)
- [ ] Settings panel open/close
- [ ] Model selector change
- [ ] Keyboard shortcuts (Ctrl+K, Escape)
- [ ] Notification center
- [ ] Token monitor
- [ ] File upload
- [ ] Message sending
- [ ] Voice input button visibility
- [ ] Sidebar resize handle
- [ ] Settings persistence (reload check)
- [ ] Modal backdrop click to close
- [ ] Skills panel open
- [ ] Workspace panel open
- [ ] Settings reset to defaults

---

## 📚 REFERENCE FILES

**Complete Guide**: `PLAYWRIGHT_E2E_GUIDE.md`
**Quick Lookup**: `PLAYWRIGHT_QUICK_REFERENCE.md`
**HTML Source**: `web/templates/index.html`
**JS Logic**: `web/static/js/app.js`

