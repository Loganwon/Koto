// ══════════════════════════════════════════════════════════════
// DocController.js — 模块 A：Canvas 渲染控制层
//
// 唯一有权操作 Univer 引擎的模块。向外暴露极简的 Facade 接口，
// 屏蔽 Univer 底层复杂度，禁止其他模块直接导入 @univerjs/*。
//
// 重要：Univer 0.5.x FDocument Facade 仅暴露 appendText / setSelection，
// 无 replaceText / getBody / getActiveRange。所有文本变更统一通过
// disposeUnit → createUnit 管线确保 paragraphs / sectionBreaks 合法。
// ══════════════════════════════════════════════════════════════

import { UniverInstanceType } from '@univerjs/core';

export class DocController {
  /** @param {import('@univerjs/core').FUniver} univerAPI */
  constructor(univerAPI) {
    this._api = univerAPI;
  }

  // ──────────────────────────────────────────
  // 1. 获取当前选区文本（优先使用浏览器原生选区）
  // ──────────────────────────────────────────
  getSelection() {
    const fullText = this.getFullText();
    if (!fullText) return null;

    // 尝试从浏览器原生 Selection 获取（Univer 0.5.x Facade 不暴露选区）
    try {
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
        const selectedText = sel.toString().trim();
        if (selectedText && selectedText.length > 0) {
          // 在文档全文中定位选中文本的偏移量
          const idx = fullText.indexOf(selectedText);
          if (idx >= 0) {
            return {
              text: selectedText,
              range: { startOffset: idx, endOffset: idx + selectedText.length },
              fullText,
            };
          }
        }
      }
    } catch (_) { /* 浏览器选区不可用，回退全文 */ }

    // 回退：返回全文
    return {
      text: fullText,
      range: { startOffset: 0, endOffset: fullText.length },
      fullText,
    };
  }

  // ──────────────────────────────────────────
  // 2. 获取全文纯文本
  // ──────────────────────────────────────────
  getFullText() {
    const doc = this._getDoc();
    if (!doc) return '';
    try {
      const snapshot = typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
      return this._streamToText(snapshot?.body?.dataStream || '').trim();
    } catch (e) {
      console.error('[DocController] getFullText 失败:', e);
      return '';
    }
  }

  // ──────────────────────────────────────────
  // 3. 在文档末尾追加文本
  // ──────────────────────────────────────────
  insertTextAtCursor(text) {
    if (!text) return false;
    const current = this.getFullText();
    return this._replaceEntireDoc(current + text);
  }

  // ──────────────────────────────────────────
  // 4. 替换指定范围内的文本（安全重建文档）
  // ──────────────────────────────────────────
  replaceRange(range, newText) {
    if (!newText) return false;
    const doc = this._getDoc();
    if (!doc) return false;

    try {
      const snapshot = typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
      const dataStream = snapshot?.body?.dataStream || '';
      const fullText = this._streamToText(dataStream);
      const start = range?.startOffset ?? 0;
      const end = range?.endOffset ?? fullText.length;

      // 拼接替换后的全文并重建文档
      if (start >= 0 && end > start && end <= fullText.length) {
        const before = fullText.substring(0, start);
        const after = fullText.substring(end);
        return this._replaceEntireDoc(before + newText + after);
      }

      // 范围不合法时直接用新文本替换全文
      return this._replaceEntireDoc(newText);
    } catch (e) {
      console.error('[DocController] replaceRange 失败:', e);
      return false;
    }
  }

  // ──────────────────────────────────────────
  // 5. 将文本内容加载到文档中（替换全部内容）
  // ──────────────────────────────────────────
  loadContent(text) {
    return this._replaceEntireDoc(text || '');
  }

  // ──────────────────────────────────────────
  // 6. 获取文档快照（JSON 格式）
  // ──────────────────────────────────────────
  getSnapshot() {
    const doc = this._getDoc();
    if (!doc) return null;
    try {
      return typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
    } catch (e) {
      console.error('[DocController] getSnapshot 失败:', e);
      return null;
    }
  }

  // ──────────────────────────────────────────
  // 7. 获取文档元信息
  // ──────────────────────────────────────────
  getDocInfo() {
    const doc = this._getDoc();
    if (!doc) return null;
    try {
      const snapshot = typeof doc.getSnapshot === 'function' ? doc.getSnapshot() : null;
      const stream = snapshot?.body?.dataStream || '';
      return {
        id: typeof doc.getId === 'function' ? doc.getId() : 'unknown',
        charCount: stream.replace(/[\r\n\0]/g, '').length,
        paragraphCount: (stream.match(/\r/g) || []).length,
      };
    } catch (e) {
      return null;
    }
  }

  // ══════════════════════════════════════════
  // 私有方法
  // ══════════════════════════════════════════

  /**
   * 安全替换整篇文档内容。
   * 流程：disposeUnit(旧) → createUnit(新) — 保证 paragraphs/sectionBreaks 合法。
   */
  _replaceEntireDoc(text) {
    try {
      const univer = window.__univer;
      if (!univer) return false;

      // 销毁当前文档单元
      const currentDoc = this._getDoc();
      if (currentDoc) {
        const id = typeof currentDoc.getId === 'function' ? currentDoc.getId() : null;
        if (id) {
          try { this._api.disposeUnit(id); } catch (_) { /* ignore */ }
        }
      }

      // 创建结构合法的新文档
      univer.createUnit(UniverInstanceType.UNIVER_DOC, {
        id: 'koto-doc-' + Date.now(),
        body: this._buildDocBody(text),
        documentStyle: {
          pageSize: { width: 595.28, height: 841.89 },
          marginTop: 72, marginBottom: 72,
          marginLeft: 90, marginRight: 90,
        },
      });

      return true;
    } catch (e) {
      console.error('[DocController] _replaceEntireDoc 失败:', e);
      return false;
    }
  }

  /**
   * 从纯文本构建合法的 Univer 文档 body（dataStream + paragraphs + sectionBreaks）。
   * 规则：每个 \n 翻译为 \r（段落），末尾固定追加 \r\n（最后段落 + 节分隔符）。
   */
  _buildDocBody(text) {
    const normalized = (text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    if (!normalized) {
      return {
        dataStream: '\r\n',
        textRuns: [],
        paragraphs: [{ startIndex: 0 }],
        sectionBreaks: [{ startIndex: 1 }],
      };
    }

    const lines = normalized.split('\n');
    let dataStream = '';
    const paragraphs = [];

    for (let i = 0; i < lines.length; i++) {
      dataStream += lines[i];
      paragraphs.push({ startIndex: dataStream.length });
      dataStream += '\r';
    }

    const sectionBreaks = [{ startIndex: dataStream.length }];
    dataStream += '\n';

    return { dataStream, textRuns: [], paragraphs, sectionBreaks };
  }

  /** 将 Univer dataStream 还原为纯文本（\r→\n，去掉尾部 \n 节分隔符） */
  _streamToText(dataStream) {
    return (dataStream || '').replace(/\n$/, '').replace(/\r/g, '\n');
  }

  _getDoc() {
    if (!this._api) return null;
    return this._api.getActiveDocument();
  }
}
