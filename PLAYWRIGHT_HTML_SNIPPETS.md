# KOTO UI - ACTUAL HTML SNIPPETS FOR REFERENCE

## 🎨 Theme Selector (Actual HTML)

\\\html
<div class="theme-selector" id="themeSelector">
    <div class="theme-option" data-theme="dark" onclick="selectTheme('dark')">
        <div class="theme-preview dark-preview">
            <div class="preview-sidebar"></div>
            <div class="preview-content"></div>
        </div>
        <span>深色</span>
    </div>
    <div class="theme-option" data-theme="light" onclick="selectTheme('light')">
        <div class="theme-preview light-preview">
            <div class="preview-sidebar"></div>
            <div class="preview-content"></div>
        </div>
        <span>浅色</span>
    </div>
    <div class="theme-option" data-theme="ocean" onclick="selectTheme('ocean')">
        <div class="theme-preview ocean-preview">
            <div class="preview-sidebar"></div>
            <div class="preview-content"></div>
        </div>
        <span>海洋</span>
    </div>
    <!-- More themes: forest, sunset, lavender, midnight, auto -->
</div>
\\\

**Test Code**:
\\\javascript
// Click each theme
const themes = ['dark', 'light', 'ocean', 'forest', 'sunset', 'lavender', 'midnight', 'auto'];
for (const theme of themes) {
  await page.click(\.theme-option[data-theme="\"]\);
  const current = await page.evaluate(() => 
    document.documentElement.getAttribute('data-theme')
  );
  expect(current).toBe(theme);
}
\\\

---

## ⚙️ Settings Button (Header)

\\\html
<button class="ghost-btn" onclick="openSettings()" title="设置">
    ⚙️ 设置
</button>
\\\

**Selectors that work**:
- \utton[title="设置"]\ ← Most specific
- \utton[onclick="openSettings()"]\ ← Also reliable
- \utton:has-text("设置")\ ← Text-based
- \.ghost-btn\ ← Too generic (many ghost buttons)

**Test Code**:
\\\javascript
await page.click('button[title="设置"]');
await page.waitForSelector('#settingsPanel.active', { timeout: 5000 });
const isOpen = await page.locator('#settingsPanel.active').isVisible();
expect(isOpen).toBe(true);
\\\

---

## 📊 Notification Button

\\\html
<button class="ghost-btn notification-btn" onclick="openNotificationCenter()" title="通知中心">
    🔔 通知
    <span class="badge" id="notificationBadge" style="display: none;">0</span>
</button>
\\\

**Selectors**:
- \utton.notification-btn\ ← Specific class
- \utton[title="通知中心"]\ ← Title attribute
- \utton:has-text("通知")\ ← Text-based

**Test Code**:
\\\javascript
// Check if badge is visible
const badge = page.locator('#notificationBadge');
const visible = await badge.isVisible();
console.log('Notification badge visible:', visible);

// Click to open
await page.click('button.notification-btn');
await page.waitForSelector('#notificationPanelModal', { visible: true });
\\\

---

## 🎯 Model Selector

\\\html
<label>默认模型</label>
<select id="settingModel" onchange="onModelChange(this.value)">
    <option value="auto">🤖 Auto (智能选择)</option>
    <option value="gemini-3-flash-preview">⚡ Gemini 3 Flash (快速)</option>
    <option value="gemini-3-pro-preview">🚀 Gemini 3 Pro (智能)</option>
    <option value="gemini-3.1-flash-image-preview">🎨 Gemini 3.1 Flash Image (图像)</option>
    <option value="gemini-2.5-flash">⚡ Gemini 2.5 Flash</option>
    <option value="gemini-2.5-pro">🚀 Gemini 2.5 Pro</option>
</select>
<p class="setting-hint" id="settingModelHint">
    Auto 会根据任务类型自动选择最合适的模型
</p>
\\\

**Test Code**:
\\\javascript
// Select a specific model
await page.selectOption('#settingModel', 'gemini-3-pro-preview');

// Verify selection
const value = await page.inputValue('#settingModel');
expect(value).toBe('gemini-3-pro-preview');

// Check hint text
const hint = await page.locator('#settingModelHint').textContent();
expect(hint).toContain('Auto');
\\\

---

## 💬 Chat Input Area

\\\html
<form class="chat-input-form" onsubmit="sendMessage(event)">
    <label class="file-upload-btn" title="附加文件">
        <input type="file" id="fileInput" onchange="handleFileSelect(event)" multiple hidden
               accept=".docx,.doc,.pdf,.txt,.md,.markdown,.rtf,.odt,.png,.jpg,.jpeg,.gif,.webp,.csv,.xlsx,.xls,.pptx,.ppt,.json"
               title="支持 Word、PDF、文本、Markdown、RTF、ODT、图片、表格等格式">
        <svg><!-- file icon --></svg>
    </label>
    <button type="button" class="voice-btn" id="voiceBtn" onclick="toggleVoice()" title="语音输入">
        <span class="voice-icon">🎙️</span>
    </button>
    <textarea 
        id="messageInput" 
        placeholder="输入消息或点击🎙️语音输入..." 
        rows="1"
        onkeydown="handleKeyDown(event)"
        oninput="autoResize(this)"
    ></textarea>
    <button type="submit" class="send-btn" id="sendBtn" title="发送">
        <svg class="send-icon"><!-- send icon --></svg>
    </button>
</form>
\\\

**Selectors**:
- \#messageInput\ - Message textarea
- \#sendBtn\ - Send button
- \#voiceBtn\ - Voice input
- \#fileInput\ - File upload

**Test Code**:
\\\javascript
// Send a message
await page.fill('#messageInput', 'Hello Koto, can you help?');
await page.click('#sendBtn');
// Or use keyboard:
await page.press('#messageInput', 'Enter');

// Verify with delay for AI response
await page.waitForTimeout(2000);
const messages = page.locator('.chat-message');
const count = await messages.count();
expect(count).toBeGreaterThan(0);
\\\

---

## 🎮 Mini Game (Hidden by Default)

\\\html
<div id="miniGamePanel" class="mini-game-panel hidden">
    <div class="mini-game-header">
        <span>🦖 放松一下</span>
        <button class="mini-game-close" onclick="hideMiniGame()">✕</button>
    </div>
    <canvas id="miniGameCanvas" width="260" height="120"></canvas>
    <div class="mini-game-hint">空格 / 点击 跳跃</div>
</div>
\\\

**State**:
- Initially: \.hidden\ class (display: none)
- Shows during waiting: \.hidden\ removed
- Canvas ID: \#miniGameCanvas\

**Test Code**:
\\\javascript
// Mini game should be hidden initially
const gamePanel = page.locator('#miniGamePanel');
let classes = await gamePanel.getAttribute('class');
expect(classes).toContain('hidden');

// Send a message to trigger game
await page.fill('#messageInput', 'Test');
await page.press('#messageInput', 'Enter');

// Game might appear if waiting is enabled
await page.waitForTimeout(1000);
\\\

---

## 🔧 Settings Panel (Truncated)

\\\html
<aside class="settings-panel" id="settingsPanel">
    <div class="close-panel" onclick="closeSettings()">×</div>
    
    <div class="settings-content">
        <!-- Theme Selector -->
        <div class="settings-section">
            <h4>🎨 外观</h4>
            <div class="theme-selector" id="themeSelector">
                <!-- 8 theme options here -->
            </div>
        </div>
        
        <!-- UI Zoom -->
        <div class="setting-item">
            <label>🔍 界面缩放
                <span class="fs-badge" id="uiZoomDisplay">100%</span>
            </label>
            <input type="range" id="uiZoomSlider" min="70" max="150" step="5" value="100"
                   oninput="setUIZoom(this.value / 100)">
            <div class="fs-presets">
                <button class="fs-preset-btn" onclick="setUIZoom(0.8)">80%</button>
                <button class="fs-preset-btn" onclick="setUIZoom(0.9)">90%</button>
                <button class="fs-preset-btn active" onclick="setUIZoom(1.0)">100%</button>
                <!-- More zoom buttons -->
            </div>
        </div>
        
        <!-- AI Settings -->
        <div class="settings-section">
            <h4>AI 设置</h4>
            
            <div class="setting-item">
                <div class="toggle-row">
                    <span class="toggle-label">🖥️ 仅使用本地模型</span>
                    <label class="toggle">
                        <input type="checkbox" id="settingLocalOnly" 
                               onchange="onLocalOnlyChange(this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            
            <div class="setting-item">
                <label>默认模型</label>
                <select id="settingModel" onchange="onModelChange(this.value)">
                    <!-- models -->
                </select>
            </div>
            
            <div class="setting-item">
                <div class="toggle-row">
                    <span class="toggle-label">显示思考过程</span>
                    <label class="toggle">
                        <input type="checkbox" id="settingShowThinking" 
                               onchange="updateSetting('ai', 'show_thinking', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            
            <!-- More settings -->
        </div>
        
        <!-- Reset & Close Buttons -->
        <div class="settings-actions">
            <button class="btn-secondary" onclick="resetSettings()">重置默认</button>
            <button class="btn-primary" onclick="closeSettings()">完成</button>
        </div>
    </div>
</aside>
\\\

**Key IDs in Settings**:
- \#settingsPanel\ - Container
- \#themeSelector\ - Theme options
- \#uiZoomSlider\ - Zoom control
- \#settingModel\ - Model dropdown
- \#settingLocalOnly\ - Local checkbox
- \#settingShowThinking\ - Thinking checkbox
- \#settingAutoSaveFiles\ - Auto-save checkbox
- \#settingVoiceAutoMode\ - Voice auto checkbox
- \#settingEnableMiniGame\ - Mini-game checkbox
- \#settingProxyEnabled\ - Proxy checkbox

**Test Pattern**:
\\\javascript
test('Settings panel controls', async ({ page }) => {
  await page.click('button[title="设置"]');
  
  // Test theme
  await page.click('.theme-option[data-theme="dark"]');
  
  // Test zoom
  await page.fill('#uiZoomSlider', '120');
  const display = await page.locator('#uiZoomDisplay').textContent();
  expect(display).toContain('120');
  
  // Test model selection
  await page.selectOption('#settingModel', 'gemini-3-pro-preview');
  
  // Test toggle
  await page.check('#settingShowThinking');
  const isChecked = await page.isChecked('#settingShowThinking');
  expect(isChecked).toBe(true);
});
\\\

---

## 📍 Sidebar Navigation

\\\html
<aside class="nav-rail chatgpt-sidebar">
    <div class="nav-brand">
        <div class="logo redesigned-logo" onclick="goToWelcome()" title="返回首页">
            <span class="logo-gradient-circle">
                <span class="logo-icon">言</span>
            </span>
            <div class="logo-copy">
                <span class="logo-text">Koto</span>
                <span class="logo-sub">Local · Gemini</span>
            </div>
        </div>
        <button class="pill-btn" onclick="showNewSessionModal()">+ 新对话</button>
    </div>
    
    <div class="nav-section">
        <div class="nav-section-head">
            <span>对话</span>
            <button class="ghost-btn" onclick="loadSessions()" title="刷新列表">↻</button>
        </div>
        <div class="sessions-list" id="sessionsList"></div>
    </div>
    
    <div class="nav-footer">
        <button id="navSkillsBtn" class="nav-skills-btn" onclick="openSkillsPanel()" title="打开 Skills 面板">
            ✨ <span>Skills 库</span>
        </button>
        <div class="status-indicator" id="statusIndicator">
            <span class="status-dot"></span>
            <div class="status-info">
                <span class="status-text">检查中...</span>
            </div>
            <button class="icon-btn-mini" onclick="checkStatus()" title="刷新">🔄</button>
        </div>
    </div>
    
    <div class="resize-handle resize-handle-sidebar" id="sidebarResizeHandle"></div>
</aside>
\\\

**Selectors**:
- `.nav-rail.chatgpt-sidebar\ - Sidebar container
- \#sessionsList\ - Active sessions
- \#navSkillsBtn\ - Skills button
- \#statusIndicator\ - Server status
- \#sidebarResizeHandle\ - Resize handle

---

## 🛠️ JavaScript Event Handlers (Key Snippets)

### Theme Selection
\\\javascript
function selectTheme(theme) {
    updateThemeSelector(theme);
    applyTheme(theme);
    updateSetting('appearance', 'theme', theme);
}

function applyTheme(theme) {
    if (theme === 'auto') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
    updateCodeTheme(theme);
}
\\\

### Settings Panel
\\\javascript
function openSettings() {
    loadSettings();
    loadMemories();
    loadSkills();
    document.getElementById('settingsPanel').classList.add('active');
}

function closeSettings() {
    document.getElementById('settingsPanel').classList.remove('active');
}
\\\

### Keyboard Handling
\\\javascript
function handleGlobalKeyDown(e) {
    if (document.querySelector('.modal-overlay.active')) return;
    
    if (e.key === 'Escape' && currentSession && isSessionGenerating(currentSession)) {
        e.preventDefault();
        document.getElementById('sendBtn')?.click();
        return;
    }
    
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        showNewSessionModal();
        return;
    }
}
\\\

---

## 📦 Complete Settings Structure (JSON Response)

\\\json
{
  "storage": {
    "workspace_dir": "C:\\\\Users\\\\username\\\\Koto\\\\workspace",
    "documents_dir": "C:\\\\Users\\\\username\\\\Koto\\\\documents",
    "images_dir": "C:\\\\Users\\\\username\\\\Koto\\\\images",
    "chats_dir": "C:\\\\Users\\\\username\\\\Koto\\\\chats"
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
    "use_local_only": false,
    "voice_language": "zh-CN",
    "voice_auto_send": true
  },
  "proxy": {
    "enabled": false,
    "manual_proxy": ""
  }
}
\\\

