// ═══════════════════════════════════════════════════════════════
// Koto 文件助手 — 主入口 (Vanilla JS + Vite)
//
// 职责：
//   1. 初始化 Univer Canvas 引擎并创建空白文档
//   2. 组装四大解耦模块（DocController / AIPanel / SocketBridge）
//   3. 建立 WebSocket 全双工实时通信
//
// 技术栈红线：
//   - 应用层代码 100% Vanilla JS，零框架依赖
//   - React/ReactDOM 仅作为 Univer UI 层的内部 peer dependency
// ═══════════════════════════════════════════════════════════════

// ─── 1. 样式导入（顺序不可变：design → ui → docs-ui → 自定义）──
import '@univerjs/design/lib/index.css';
import '@univerjs/ui/lib/index.css';
import '@univerjs/docs-ui/lib/index.css';
import './style.css';

// ─── 2. Univer 核心模块 ──
import { Univer, UniverInstanceType, LocaleType, FUniver } from '@univerjs/core';
import { defaultTheme } from '@univerjs/design';
import { UniverRenderEnginePlugin } from '@univerjs/engine-render';
import { UniverUIPlugin } from '@univerjs/ui';
import { UniverDocsPlugin } from '@univerjs/docs';
import { UniverDocsUIPlugin } from '@univerjs/docs-ui';
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula';

// Facade 扩展 (为 FUniver 添加文档操作方法)
import '@univerjs/ui/facade';
import '@univerjs/docs-ui/facade';

// ─── 2b. Locale 数据（ZH_CN）──
import DesignZhCN from '@univerjs/design/locale/zh-CN';
import UIZhCN from '@univerjs/ui/locale/zh-CN';
import DocsUIZhCN from '@univerjs/docs-ui/locale/zh-CN';

// ─── 3. Koto 文件助手四大模块 ──
import { DocController } from './src/DocController.js';
import { SocketBridge } from './src/SocketBridge.js';
import { AIPanel } from './src/AIPanel.js';
import { FileManager } from './src/FileManager.js';
import { FloatingToolbar } from './src/FloatingToolbar.js';
import { DocxViewer } from './src/DocxViewer.js';
import { PptxViewer } from './src/PptxViewer.js';
import { ExcelViewer } from './src/ExcelViewer.js';


// ═══════════════════════════════════════════════════════════════
// 空白 A4 文档数据模型
// ═══════════════════════════════════════════════════════════════
const BLANK_A4_DOC = {
  id: 'koto-doc-001',
  body: {
    dataStream: '\r\n',
    textRuns: [],
    paragraphs: [{ startIndex: 0 }],
    sectionBreaks: [{ startIndex: 1 }],
  },
  documentStyle: {
    pageSize: { width: 595.28, height: 841.89 },
    marginTop: 72,
    marginBottom: 72,
    marginLeft: 90,
    marginRight: 90,
  },
};


// ═══════════════════════════════════════════════════════════════
// 初始化 Univer 引擎
// ═══════════════════════════════════════════════════════════════
function initUniver() {
  const univer = new Univer({
    theme: defaultTheme,
    locale: LocaleType.ZH_CN,
    locales: {
      [LocaleType.ZH_CN]: {
        ...DesignZhCN,
        ...UIZhCN,
        ...DocsUIZhCN,
      },
    },
  });

  // 按依赖顺序注册插件链 (官方最小 Docs 插件集)
  univer.registerPlugin(UniverRenderEnginePlugin);
  univer.registerPlugin(UniverFormulaEnginePlugin);
  univer.registerPlugin(UniverUIPlugin, { container: 'univer-container' });
  univer.registerPlugin(UniverDocsPlugin);
  univer.registerPlugin(UniverDocsUIPlugin);

  // 创建空白 A4 文档
  univer.createUnit(UniverInstanceType.UNIVER_DOC, BLANK_A4_DOC);

  // 生成 Facade API（AI Agent 操控文档的唯一入口）
  const api = FUniver.newAPI(univer);

  // 暴露到全局供调试
  window.univerAPI = api;
  window.__univer = univer;

  console.log('[Koto] Univer 引擎初始化完成');
  return api;
}


// ═══════════════════════════════════════════════════════════════
// 应用启动 — 组装所有模块
// ═══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  try {
    // 1. 初始化 Univer Canvas 引擎
    const univerAPI = initUniver();

    // 2. 创建 DocController（唯一操控 Univer 的防腐层）
    const docController = new DocController(univerAPI);

    // 3. 创建 SocketBridge（WebSocket 全双工通信网关）
    const serverUrl = window.location.port === '5173'
      ? 'http://127.0.0.1:5000'   // Vite dev → Flask dev
      : window.location.origin;    // 生产构建 → 同源
    const socketBridge = new SocketBridge(serverUrl, docController);

    // 4. 创建 AIPanel（右侧交互面板，绑定按钮与对话流）
    const aiPanel = new AIPanel('right-ai-panel', docController, socketBridge);

    // 4b. 创建 FloatingToolbar（选区浮动 AI 工具栏）
    const floatingToolbar = new FloatingToolbar(docController, socketBridge, aiPanel);

    // 4c. 创建 DocxViewer（Word 仿真 DOCX 只读查看器）
    const docxViewer = new DocxViewer('center-doc');

    // 4d. 创建 PptxViewer（可编辑 PowerPoint 查看器）
    const pptxViewer = new PptxViewer('center-doc');

    // 4e. 创建 ExcelViewer（Univer Sheets Excel 查看器）
    const excelViewer = new ExcelViewer('center-doc');

    // 5. 创建 FileManager（左侧文件管理面板）
    const fileManager = new FileManager('left-sidebar', docController, (content, docId) => {
      // 文档切换回调：将新文档内容加载到 Univer
      if (content) {
        docController.loadContent(content);
      } else {
        // 空白文档：清空编辑器
        docController.loadContent('');
      }
      // Reset AI conversation history when switching to a different file
      aiPanel.resetHistory(docId);
    }, docxViewer, pptxViewer, excelViewer);

    // 6. 自动保存（每 30 秒）
    setInterval(() => fileManager.save(), 30000);

    // 7. 启动 WebSocket 连接
    socketBridge.init();

    // 8. Drop-zone on #center-doc — accept chart images (from AI panel) and OS image files.
    // NOTE: Use capture phase (3rd arg = true) so our handler fires BEFORE Univer's internal
    // canvas drag listeners — this prevents the Univer "不支持" toast when dragging image files.
    const centerDoc = document.getElementById('center-doc');
    if (centerDoc) {
      // Helper: true if dataTransfer contains at least one image file from the OS
      const _hasOsImage = (dt) => {
        if (dt.items) {
          return Array.from(dt.items).some(item => item.kind === 'file' && item.type.startsWith('image/'));
        }
        // Fallback (Firefox): types includes 'Files', check after drop via dt.files
        return dt.types.includes('Files');
      };

      // ── dragover: capture phase ──────────────────────────────────────────────
      centerDoc.addEventListener('dragover', (e) => {
        const isChart   = e.dataTransfer.types.includes('application/koto-chart-id');
        const isOsImage = _hasOsImage(e.dataTransfer);
        if (isChart || isOsImage) {
          e.preventDefault();
          e.stopPropagation();   // prevent Univer canvas from seeing it
          e.dataTransfer.dropEffect = 'copy';
          centerDoc.classList.add('koto-drop-active');
        }
      }, true);  // capture

      // ── dragleave ────────────────────────────────────────────────────────────
      centerDoc.addEventListener('dragleave', (e) => {
        if (!centerDoc.contains(e.relatedTarget)) {
          centerDoc.classList.remove('koto-drop-active');
        }
      });

      // ── drop: capture phase ──────────────────────────────────────────────────
      centerDoc.addEventListener('drop', (e) => {
        centerDoc.classList.remove('koto-drop-active');

        // ── A. OS image file drop (jpg/png/gif/webp…) ──
        const imageFiles = Array.from(e.dataTransfer.files || []).filter(f => f.type.startsWith('image/'));
        if (imageFiles.length > 0) {
          e.preventDefault();
          e.stopPropagation();
          const file = imageFiles[0];
          const reader = new FileReader();
          reader.onload = (ev) => {
            const imgSrc = ev.target.result;
            if (docxViewer && docxViewer.isActive()) {
              docxViewer.appendImage(imgSrc, file.name);
            } else {
              docController.insertImageAtEnd(imgSrc, file.name);
            }
          };
          reader.readAsDataURL(file);
          return;
        }

        // ── B. Chart image dragged from AI panel (ID-based) ──
        const imgId   = e.dataTransfer.getData('application/koto-chart-id');
        const imgName = e.dataTransfer.getData('application/koto-chart-name') || 'chart.png';
        if (!imgId) return;
        e.preventDefault();

        const entry  = window._kotoChartStore && window._kotoChartStore[imgId];
        const imgSrc = entry?.src;
        if (!imgSrc) return;

        if (docxViewer && docxViewer.isActive()) {
          docxViewer.appendImage(imgSrc, imgName);
        } else {
          docController.insertImageAtEnd(imgSrc, imgName);
        }
      }, true);  // capture
    }

    // 暴露到全局供调试
    window.__koto = { docController, socketBridge, aiPanel, fileManager, floatingToolbar, docxViewer, pptxViewer, excelViewer };

    console.log('[Koto] 文件助手启动完成');
  } catch (err) {
    console.error('[Koto] 启动失败:', err);
    // 出错时显示诊断面板
    const diag = document.getElementById('koto-diag');
    if (diag) {
      diag.style.display = 'block';
      const d = document.createElement('div');
      d.textContent = '❌ ' + err.message;
      diag.appendChild(d);
    }
  }
});
