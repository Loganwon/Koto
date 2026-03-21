# Koto Web UI - Playwright E2E Testing Guide

## Project Structure

- **Main Template**: `C:\repos\Koto\web\templates\index.html` (179 KB - complete UI)
- **Main JavaScript**: `C:\repos\Koto\web\static\js\app.js`
- **CSS**: `C:\repos\Koto\web\static\css\style.css`
- **CSS**: `C:\repos\Koto\web\static\css\skill_marketplace.css`

---

## 🎯 UI Elements - Element Selectors

### Navigation/Header & Buttons

| Element | Selector | Type | Purpose |
|---------|----------|------|---------|
| Settings Button | `button[onclick="openSettings()"]` | Button | Opens settings panel |
| Settings Button (Alt) | `button[title="设置"]` | Button | Settings (Chinese) |
| Notification Button | `button.notification-btn` | Button | Opens notification center |
| Notification Badge | `#notificationBadge` | Badge | Shows notification count |
| Token Monitor Chip | `#tokenChip` | Div | Shows token usage |
| Token Panel | `#tokenPanel` | Div | Token usage panel (hidden by default) |
| Shadow Watcher Button | `#shadowToggleBtn` | Button | Shadow tracking button |
| New Session Button | `button[onclick="showNewSessionModal()"]` | Button | Create new chat |

### Theme Selector

| Element | Selector | Type | Data Attribute |
|---------|----------|------|-----------------|
| Dark Theme | `.theme-option[data-theme="dark"]` | Div | `data-theme="dark"` |
| Light Theme | `.theme-option[data-theme="light"]` | Div | `data-theme="light"` |
| Ocean Theme | `.theme-option[data-theme="ocean"]` | Div | `data-theme="ocean"` |
| Forest Theme | `.theme-option[data-theme="forest"]` | Div | `data-theme="forest"` |
| Sunset Theme | `.theme-option[data-theme="sunset"]` | Div | `data-theme="sunset"` |
| Lavender Theme | `.theme-option[data-theme="lavender"]` | Div | `data-theme="lavender"` |
| Midnight Theme | `.theme-option[data-theme="midnight"]` | Div | `data-theme="midnight"` |
| Auto Theme | `.theme-option[data-theme="auto"]` | Div | `data-theme="auto"` |
| Theme Selector Container | `#themeSelector` | Div | Container for all themes |

### Settings Panel Controls

| Element | Selector | Type | Purpose |
|---------|----------|------|---------|
| Settings Panel | `#settingsPanel` | Aside | Main settings sidebar |
| Close Settings | `button[onclick="closeSettings()"]` | Button | Close settings |
| Model Selector | `#settingModel` | Select | Choose AI model |
| Local Only | `#settingLocalOnly` | Checkbox | Use only local models |
| Auto Save Files | `#settingAutoSaveFiles` | Checkbox | Auto-save generated files |
| Show Thinking | `#settingShowThinking` | Checkbox | Show AI reasoning |
| Show Task Type | `#settingShowTaskType` | Checkbox | Display task labels |
| Voice Auto Mode | `#settingVoiceAutoMode` | Checkbox | Auto-upload voice |
| Mini Game | `#settingEnableMiniGame` | Checkbox | Enable mini-game while waiting |
| Proxy Enabled | `#settingProxyEnabled` | Checkbox | Enable network proxy |
| Manual Proxy | `#settingManualProxy` | Input | Proxy address (e.g., http://127.0.0.1:7890) |
| UI Zoom Slider | `#uiZoomSlider` | Range | Scale UI (70-150%) |
| UI Zoom Display | `#uiZoomDisplay` | Badge | Shows zoom percentage |
| Reset Button | `button[onclick="resetSettings()"]` | Button | Reset to defaults |

### Chat Interface

| Element | Selector | Type | Purpose |
|---------|----------|------|---------|
| Chat Messages | `#chatMessages` | Div | Main chat history area |
| Message Input | `#messageInput` | Textarea | Type messages |
| Send Button | `#sendBtn` | Button | Submit message |
| File Upload | `#fileInput` | Input | Attach files |
| Voice Button | `#voiceBtn` | Button | Voice input |
| Welcome Screen | `#welcomeScreen` | Div | Initial welcome |
| Mini Game Panel | `#miniGamePanel` | Div | Waiting game |
| Mini Game Canvas | `#miniGameCanvas` | Canvas | Dino game |

### Sidebar & Panels

| Element | Selector | Type | Purpose |
|---------|----------|------|---------|
| Sidebar | `.nav-rail.chatgpt-sidebar` | Aside | Left navigation |
| Logo | `.logo.redesigned-logo` | Div | Koto logo |
| Sessions List | `#sessionsList` | Div | Chat sessions |
| Skills Button | `#navSkillsBtn` | Button | Open skills |
| Status Indicator | `#statusIndicator` | Div | Server status |
| Workspace Panel | `#workspacePanel` | Aside | File browser |
| Skills Panel | `#skillsPanel` | Aside | Skills management |

---

## 🔌 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` / `Cmd+K` | New chat session |
| `Escape` | Stop message generation (if generating) |
| `Enter` | Send message |
| `Shift+Enter` | New line in message |
| `Escape` | Close modal dialogs |

### Implementation Details
- **Handler**: `handleGlobalKeyDown(e)` in `app.js`
- **Registered**: `window.addEventListener('keydown', handleGlobalKeyDown)`
- **Key Points**:
  - Skips if `.modal-overlay.active` is present
  - Escape stops generation only if `isSessionGenerating(currentSession)` is true

---

## 🎨 Theme System

### How to Select Theme
`javascript
// JavaScript function:
selectTheme('dark')       // Dark mode
selectTheme('light')      // Light mode
selectTheme('ocean')      // Ocean blue
selectTheme('forest')     // Forest green
selectTheme('sunset')     // Sunset orange
selectTheme('lavender')   // Lavender purple
selectTheme('midnight')   // Midnight blue
selectTheme('auto')       // Follow system preference
`

### Get Current Theme
`javascript
document.documentElement.getAttribute('data-theme')
// Returns: 'dark', 'light', 'ocean', etc.
`

### CSS Variables
The UI uses custom properties:
- `--bg-primary`, `--bg-secondary`, `--bg-tertiary` - Backgrounds
- `--text-primary`, `--text-secondary`, `--text-muted` - Text colors
- `--accent-primary`, `--accent-secondary`, `--accent-danger` - Accents
- `--border-color` - Borders

---

## 🧪 Playwright Test Examples

### Test 1: Open and Change Theme
\\\javascript
test('Change theme to dark', async ({ page }) => {
  await page.goto('http://localhost:3000')
  
  // Click settings
  await page.click('button[title="设置"]')
  await page.waitForSelector('#settingsPanel.active')
  
  // Click dark theme
  await page.click('.theme-option[data-theme="dark"]')
  
  // Verify
  const theme = await page.evaluate(() => 
    document.documentElement.getAttribute('data-theme')
  )
  expect(theme).toBe('dark')
})
\\\

### Test 2: Send Message
\\\javascript
test('Send message', async ({ page }) => {
  await page.goto('http://localhost:3000')
  
  // Type message
  await page.fill('#messageInput', 'Hello Koto')
  
  // Send with Enter
  await page.press('#messageInput', 'Enter')
  
  // Verify message appears in chat
  await page.waitForSelector('.chat-message:has-text("Hello Koto")')
})
\\\

### Test 3: Keyboard Shortcut
\\\javascript
test('Ctrl+K opens new session', async ({ page }) => {
  await page.goto('http://localhost:3000')
  
  // Press Ctrl+K
  await page.keyboard.press('Control+K')
  
  // Modal should appear
  await page.waitForSelector('#newSessionModal')
})
\\\

### Test 4: Upload File
\\\javascript
test('Upload file', async ({ page }) => {
  await page.goto('http://localhost:3000')
  
  // Upload file
  const fileInput = page.locator('#fileInput')
  await fileInput.setInputFiles('/path/to/document.pdf')
  
  // Verify in file preview
  await page.waitForSelector('#filePreview')
})
\\\

---

## 📋 Settings API

### Endpoint
- **Method**: GET/POST
- **URL**: `/api/settings`

### Response Structure
\\\json
{
  "storage": {
    "workspace_dir": "/path/to/workspace",
    "documents_dir": "/path/to/documents",
    "images_dir": "/path/to/images",
    "chats_dir": "/path/to/chats"
  },
  "appearance": {
    "theme": "dark",
    "ui_zoom": 1.0
  },
  "ai": {
    "default_model": "gemini-3-flash-preview",
    "show_thinking": false,
    "show_task_type": false,
    "auto_save_files": true,
    "voice_auto_mode": true,
    "enable_mini_game": true,
    "use_local_only": false
  },
  "proxy": {
    "enabled": false,
    "manual_proxy": ""
  }
}
\\\

### Update Setting (JS)
\\\javascript
updateSetting('appearance', 'theme', 'dark')
updateSetting('ai', 'show_thinking', true)
updateSetting('ai', 'default_model', 'gemini-3-pro-preview')
\\\

---

## 🧠 Global State

### Variables
| Name | Type | Purpose |
|------|------|---------|
| `currentSession` | Object | Active chat session |
| `selectedFiles` | Array | Attached files |
| `selectedModel` | String | Selected AI model |
| `currentSettings` | Object | Loaded settings |

### Helper Functions
\\\javascript
isSessionGenerating(currentSession)  // Check if generating
loadSettings()                        // Fetch settings
applyTheme(theme)                     // Apply theme
\\\

---

## 🐛 Debug Tips

### Console Commands
\\\javascript
// Check current theme
document.documentElement.getAttribute('data-theme')

// Check if modal open
document.querySelector('.modal-overlay.active')

// Check settings panel
document.getElementById('settingsPanel').classList.contains('active')

// View all settings
console.log(currentSettings)

// Check if generating
isSessionGenerating(currentSession)
\\\

---

## 📦 File References

- Main HTML: `web/templates/index.html` (179 KB)
- App JS: `web/static/js/app.js`
- Framework JS: `web/static/js/app-framework.js`
- CSS: `web/static/css/style.css`
- Skill CSS: `web/static/css/skill_marketplace.css`

