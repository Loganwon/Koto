# 🎯 KOTO UI - QUICK REFERENCE FOR PLAYWRIGHT E2E TESTS

## ⚡ Most Used Selectors

### Settings & Theme (Most Common Tests)
\\\
#settingsPanel              // Main settings panel
#themeSelector              // Theme selector container
.theme-option[data-theme="dark"]   // Each theme option
#settingModel               // Model dropdown
#settingLocalOnly           // Local-only checkbox
\\\

### Chat Interface
\\\
#messageInput               // Message textarea
#sendBtn                    // Send button
#chatMessages               // Chat history container
#voiceBtn                   // Voice input button
#fileInput                  // File upload
\\\

### Buttons (Header)
\\\
button[title="设置"]          // Settings button (most reliable)
button.notification-btn     // Notification center
#shadowToggleBtn            // Shadow watcher
#tokenChip                  // Token monitor
\\\

---

## ⌨️ Keyboard Shortcuts
\\\
Ctrl+K / Cmd+K              // New session
Escape (while generating)   // Stop message
Enter                       // Send message
Shift+Enter                 // New line
\\\

---

## 📋 Critical IDs (Search in HTML)
\\\
id="settingsPanel"          // Settings sidebar
id="settingModel"           // AI model selector
id="themeSelector"          // Theme picker container
id="chatMessages"           // Chat history
id="messageInput"           // Message textarea
id="notificationBadge"      // Notification count badge
id="tokenPanel"             // Token usage panel
id="miniGamePanel"          // Dino game (hidden)
id="voiceBtn"               // Voice input
id="shadowToggleBtn"        // Shadow feature button
\\\

---

## 🎨 Theme Values (Click These)
\\\
data-theme="dark"           // Dark mode
data-theme="light"          // Light mode
data-theme="ocean"          // Ocean blue
data-theme="forest"         // Forest green
data-theme="sunset"         // Sunset orange
data-theme="lavender"       // Lavender purple
data-theme="midnight"       // Midnight blue
data-theme="auto"           // System preference
\\\

---

## ✅ Common Test Template

\\\javascript
import { test, expect } from '@playwright/test';

test('Change theme to dark', async ({ page }) => {
  // Navigate
  await page.goto('http://localhost:3000');
  
  // Open settings
  await page.click('button[title="设置"]');
  await page.waitForSelector('#settingsPanel.active');
  
  // Select theme
  await page.click('.theme-option[data-theme="dark"]');
  
  // Verify
  const theme = await page.evaluate(() => 
    document.documentElement.getAttribute('data-theme')
  );
  expect(theme).toBe('dark');
  
  // Close settings
  await page.click('button[onclick="closeSettings()"]');
});
\\\

---

## 🔍 Check States (in Tests)

\\\javascript
// Is settings open?
await page.locator('#settingsPanel.active').isVisible();

// What's the current theme?
await page.evaluate(() => 
  document.documentElement.getAttribute('data-theme')
);

// Is a modal open?
await page.locator('.modal-overlay.active').count() > 0;

// Is notification badge visible?
await page.locator('#notificationBadge').isVisible();

// Check if message was sent
await page.locator('text=Hello Koto').isVisible();
\\\

---

## 📍 Files to Reference

Main template (all IDs/classes):
  C:\repos\Koto\web\templates\index.html

JavaScript logic (functions, state):
  C:\repos\Koto\web\static\js\app.js

CSS themes & styles:
  C:\repos\Koto\web\static\css\style.css

---

## 🚀 Example: Full Settings Flow Test

\\\javascript
test('Complete settings workflow', async ({ page }) => {
  await page.goto('http://localhost:3000');
  
  // 1. Open settings
  await page.click('button[title="设置"]');
  await page.waitForSelector('#settingsPanel.active');
  
  // 2. Change model
  await page.selectOption('#settingModel', 'gemini-3-pro-preview');
  
  // 3. Toggle show thinking
  await page.check('#settingShowThinking');
  
  // 4. Change theme
  await page.click('.theme-option[data-theme="ocean"]');
  
  // 5. Verify theme
  const theme = await page.evaluate(() =>
    document.documentElement.getAttribute('data-theme')
  );
  expect(theme).toBe('ocean');
  
  // 6. Close
  await page.click('button[onclick="closeSettings()"]');
});
\\\

---

## 🎯 Data Attributes Found

.theme-option[data-theme="X"]    // Use data-theme to select theme
.theme-preview.dark-preview      // Visual preview styles
.skill-card[data-hidden]          // Hidden skill cards
.modal-overlay.active             // Active modal state

---

## 📊 Key HTML Structure

\\\
body.loading                       // Initial load state
#settingsPanel (aside)             // Right settings sidebar
#chatMessages (div)                // Chat container
#messageInput (textarea)           // Input field
.theme-option (div)                // 8 theme options
.modal-overlay (div)               // Modal backdrop
#voicePanelModal (div)             // Voice panel
#notificationPanelModal (div)      // Notifications
\\\

