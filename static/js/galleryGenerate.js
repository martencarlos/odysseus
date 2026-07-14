/**
 * galleryGenerate.js — text-to-image generation panel inside the Gallery modal.
 *
 * Lives on the "Generate" tab. Lets the user pick a prompt, an image-capable
 * model (or auto-detect), an aspect ratio, a quality, and an optional style
 * hint, then generate an image that is stored in the gallery under the
 * "generated" album. The result can be kept, copied, opened in the editor,
 * or discarded.
 */

import uiModule from './ui.js';
import { openEditor } from './galleryEditor.js';

const API_BASE = window.location.origin;

// Cached model list (refreshed on tab open). Each item:
//   { id, label, model, source, kind: 'cloud' | 'local' }
let _models = [];
let _modelsLoaded = false;

// Last generation result retained for the action bar (keep/copy/edit/discard).
let _lastResult = null;

const ASPECT_PRESETS = [
  { value: 'square',    label: 'Square 1:1',    size: '1024x1024' },
  { value: 'portrait',  label: 'Portrait 2:3',  size: '1024x1536' },
  { value: 'landscape', label: 'Landscape 3:2', size: '1536x1024' },
  { value: 'wide',      label: 'Wide 16:9',     size: '1536x864'  },
];

const QUALITY_OPTIONS = [
  { value: 'auto',   label: 'Auto' },
  { value: 'low',    label: 'Low (fastest)' },
  { value: 'medium', label: 'Medium' },
  { value: 'high',   label: 'High (slowest)' },
];

const STYLE_CHIPS = [
  'photorealistic', 'cinematic', 'digital art', 'oil painting',
  'watercolor', 'anime', '3D render', 'minimalist', 'pixel art',
];

/**
 * Render the Generate tab into #gallery-generate-container. Called once when
 * the gallery modal mounts (the container is created in gallery.js).
 */
export function renderGenerateTab() {
  const container = document.getElementById('gallery-generate-container');
  if (!container) return;
  container.innerHTML = `
    <div class="gallery-generate">
      <div class="gallery-generate-form">
        <label class="gallery-gen-label">
          Prompt
          <textarea id="gallery-gen-prompt" class="gallery-gen-textarea" rows="3"
            placeholder="Describe the image you want to generate..."></textarea>
        </label>

        <div class="gallery-gen-row">
          <label class="gallery-gen-label gallery-gen-field">
            Model
            <select id="gallery-gen-model" class="gallery-gen-select">
              <option value="">Auto-detect (best available)</option>
            </select>
          </label>
          <label class="gallery-gen-label gallery-gen-field">
            Aspect ratio
            <select id="gallery-gen-aspect" class="gallery-gen-select">
              ${ASPECT_PRESETS.map(p => `<option value="${p.value}">${p.label}</option>`).join('')}
            </select>
          </label>
        </div>

        <div class="gallery-gen-row">
          <label class="gallery-gen-label gallery-gen-field">
            Quality
            <select id="gallery-gen-quality" class="gallery-gen-select">
              ${QUALITY_OPTIONS.map(q => `<option value="${q.value}">${q.label}</option>`).join('')}
            </select>
          </label>
          <label class="gallery-gen-label gallery-gen-field">
            Style <span class="gallery-gen-hint">(optional)</span>
            <input type="text" id="gallery-gen-style" class="gallery-gen-input"
              placeholder="e.g. cinematic, watercolor..." list="gallery-gen-style-list" />
            <datalist id="gallery-gen-style-list">
              ${STYLE_CHIPS.map(s => `<option value="${s}"></option>`).join('')}
            </datalist>
          </label>
        </div>

        <div class="gallery-gen-actions">
          <button class="gallery-select-btn gallery-gen-generate" id="gallery-gen-generate">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
            Generate
          </button>
        </div>
      </div>

      <div class="gallery-gen-result" id="gallery-gen-result" hidden>
        <div class="gallery-gen-result-image-wrap">
          <img id="gallery-gen-result-img" alt="Generated image" />
          <div class="gallery-gen-result-loading" id="gallery-gen-result-loading" hidden>
            <div class="gallery-gen-spinner"></div>
            <div class="gallery-gen-result-status" id="gallery-gen-result-status">Generating…</div>
          </div>
        </div>
        <div class="gallery-gen-result-meta" id="gallery-gen-result-meta"></div>
        <div class="gallery-gen-result-actions" id="gallery-gen-result-actions" hidden>
          <button class="gallery-select-btn" id="gallery-gen-keep" title="Keep the image in your gallery">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><polyline points="20 6 9 17 4 12"/></svg>
            Keep
          </button>
          <button class="gallery-select-btn" id="gallery-gen-copy" title="Copy image to clipboard">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            Copy
          </button>
          <button class="gallery-select-btn" id="gallery-gen-edit" title="Open in the image editor">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
            Edit
          </button>
          <button class="gallery-select-btn gallery-gen-discard" id="gallery-gen-discard" title="Delete this image">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
            Discard
          </button>
        </div>
      </div>

      <div class="gallery-gen-empty" id="gallery-gen-empty">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
        <p>Describe an image and hit Generate.<br/>Results are saved to the “generated” album.</p>
      </div>
    </div>
  `;
  _wireForm();
  // Populate the model picker asynchronously.
  refreshModels();
}

/**
 * Fetch the list of image-capable models from the backend and fill the
 * <select>. Safe to call repeatedly — reuses the cached list within the
 * gallery session and refetches when forceRefresh is true.
 */
export async function refreshModels(forceRefresh = false) {
  const sel = document.getElementById('gallery-gen-model');
  if (!sel) return;
  if (_modelsLoaded && !forceRefresh) {
    _populateModelSelect(sel);
    return;
  }
  // Keep the auto-detect option but disable interaction while loading.
  sel.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/gallery/image-models`, { credentials: 'include' });
    if (res.ok) {
      const data = await res.json();
      _models = Array.isArray(data.models) ? data.models : [];
      _modelsLoaded = true;
    }
  } catch (e) {
    // Network / auth — leave the picker with just auto-detect.
    _models = [];
  } finally {
    _populateModelSelect(sel);
    sel.disabled = false;
  }
}

function _populateModelSelect(sel) {
  const prev = sel.value || '';
  let html = '<option value="">Auto-detect (best available)</option>';
  // Group by kind so cloud / provider / local models are easy to tell apart.
  const groups = { cloud: [], provider: [], local: [] };
  for (const m of _models) (groups[m.kind] || groups.provider).push(m);
  const _GROUP_LABELS = { cloud: 'Cloud', provider: 'Provider', local: 'Local / self-hosted' };
  for (const kind of ['cloud', 'provider', 'local']) {
    const items = groups[kind];
    if (!items || !items.length) continue;
    html += `<optgroup label="${_escAttr(_GROUP_LABELS[kind])}">`;
    for (const m of items) {
      const val = _encodeModelValue(m);
      html += `<option value="${_escAttr(val)}">${_escHtml(m.label)}</option>`;
    }
    html += '</optgroup>';
  }
  sel.innerHTML = html;
  // Preserve the previous selection if still present.
  if (prev && Array.from(sel.options).some(o => o.value === prev)) {
    sel.value = prev;
  }
}

// Encode a model descriptor as a single option value. We store the model id
// plus a source tag so the backend can route cloud vs. local correctly.
function _encodeModelValue(m) {
  return `${m.model}::${m.source || ''}::${m.kind || ''}`;
}

function _decodeModelValue(v) {
  if (!v) return null;
  const parts = v.split('::');
  return { model: parts[0] || '', source: parts[1] || '', kind: parts[2] || '' };
}

function _wireForm() {
  const genBtn = document.getElementById('gallery-gen-generate');
  const promptEl = document.getElementById('gallery-gen-prompt');
  if (genBtn) {
    genBtn.addEventListener('click', () => _onGenerate());
  }
  if (promptEl) {
    // Ctrl/Cmd+Enter triggers generation from the textarea.
    promptEl.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        _onGenerate();
      }
    });
  }
  const keepBtn = document.getElementById('gallery-gen-keep');
  const copyBtn = document.getElementById('gallery-gen-copy');
  const editBtn = document.getElementById('gallery-gen-edit');
  const discardBtn = document.getElementById('gallery-gen-discard');
  keepBtn?.addEventListener('click', () => _onKeep());
  copyBtn?.addEventListener('click', () => _onCopy());
  editBtn?.addEventListener('click', () => _onEdit());
  discardBtn?.addEventListener('click', () => _onDiscard());
}

async function _onGenerate() {
  const promptEl = document.getElementById('gallery-gen-prompt');
  const prompt = (promptEl?.value || '').trim();
  if (!prompt) {
    uiModule.showToast('Enter a prompt first');
    promptEl?.focus();
    return;
  }
  const modelSel = document.getElementById('gallery-gen-model');
  const aspectSel = document.getElementById('gallery-gen-aspect');
  const qualitySel = document.getElementById('gallery-gen-quality');
  const styleEl = document.getElementById('gallery-gen-style');

  const modelVal = modelSel ? modelSel.value : '';
  const modelDesc = _decodeModelValue(modelVal);
  // The backend's auto-detect covers cloud + local; for an explicit local
  // model we still pass the model id (do_generate_image resolves it).
  const model = modelDesc ? modelDesc.model : '';
  const size = aspectSel ? ASPECT_PRESETS.find(p => p.value === aspectSel.value)?.size || 'square' : 'square';
  const quality = qualitySel ? qualitySel.value : 'auto';
  const style = (styleEl?.value || '').trim();

  _showLoading(true, 'Generating…');
  _setActionsEnabled(false);

  try {
    const res = await fetch(`${API_BASE}/api/gallery/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ prompt, model, size, quality, style }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      const err = (data && (data.detail || data.error)) || `Generation failed (${res.status})`;
      _showError(err);
      return;
    }
    _lastResult = data;
    _renderResult(data);
  } catch (e) {
    _showError(String(e && e.message || e));
  }
}

function _renderResult(data) {
  const empty = document.getElementById('gallery-gen-empty');
  const result = document.getElementById('gallery-gen-result');
  const img = document.getElementById('gallery-gen-result-img');
  const meta = document.getElementById('gallery-gen-result-meta');
  const actions = document.getElementById('gallery-gen-result-actions');
  const loading = document.getElementById('gallery-gen-result-loading');
  const status = document.getElementById('gallery-gen-result-status');
  if (empty) empty.hidden = true;
  if (result) result.hidden = false;
  if (loading) loading.hidden = true;
  if (actions) actions.hidden = false;

  if (img && data.url) {
    // Cache-bust: the URL is content-addressed but a fresh result with the
    // same filename (rare) should still repaint.
    img.src = data.url + (data.url.includes('?') ? '&' : '?') + '_t=' + Date.now();
  }
  if (meta) {
    const bits = [];
    if (data.model) bits.push(data.model);
    if (data.size) bits.push(data.size);
    if (data.quality) bits.push(data.quality);
    if (data.style) bits.push(`style: ${data.style}`);
    meta.innerHTML = _escHtml(bits.join(' · '));
  }
  _setActionsEnabled(true);
  // Refresh the gallery grid so the new image appears in Photos / generated album.
  try { window.dispatchEvent(new CustomEvent('gallery-refresh', { detail: { source: 'generate' } })); } catch (_) {}
  uiModule.showToast('Image generated — saved to “generated” album');
}

function _showError(msg) {
  _showLoading(false);
  _setActionsEnabled(false);
  uiModule.showError ? uiModule.showError(msg) : uiModule.showToast(msg);
}

function _showLoading(loading, statusText) {
  const loadingEl = document.getElementById('gallery-gen-result-loading');
  const status = document.getElementById('gallery-gen-result-status');
  const empty = document.getElementById('gallery-gen-empty');
  const result = document.getElementById('gallery-gen-result');
  const actions = document.getElementById('gallery-gen-result-actions');
  const img = document.getElementById('gallery-gen-result-img');
  if (loading) {
    if (empty) empty.hidden = true;
    if (result) result.hidden = false;
    // Clear any previous image so a stale/broken <img> doesn't flash behind
    // the loading overlay while the new generation is in flight.
    if (img) img.removeAttribute('src');
    if (loadingEl) loadingEl.hidden = false;
    if (status) status.textContent = statusText || 'Generating…';
    if (actions) actions.hidden = true;
  } else {
    if (loadingEl) loadingEl.hidden = true;
  }
}

function _setActionsEnabled(enabled) {
  ['gallery-gen-keep', 'gallery-gen-copy', 'gallery-gen-edit', 'gallery-gen-discard']
    .forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = !enabled;
    });
}

// Keep: image is already saved in the gallery + generated album. This just
// clears the result panel and resets the form for the next generation.
function _onKeep() {
  _resetResult();
  const promptEl = document.getElementById('gallery-gen-prompt');
  if (promptEl) {
    promptEl.value = '';
    promptEl.focus();
  }
  uiModule.showToast('Kept in gallery');
}

async function _onCopy() {
  if (!_lastResult?.url) return;
  try {
    const res = await fetch(_lastResult.url, { credentials: 'include' });
    if (!res.ok) throw new Error('Could not fetch image');
    const blob = await res.blob();
    try {
      await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
      uiModule.showToast('Copied to clipboard');
    } catch (e) {
      // Fallback: write the URL to the clipboard if image copy is unsupported.
      await uiModule.copyToClipboard(_lastResult.url);
      uiModule.showToast('Image URL copied');
    }
  } catch (e) {
    uiModule.showToast('Copy failed');
  }
}

function _onEdit() {
  if (!_lastResult?.url) return;
  const label = (_lastResult.prompt || '').slice(0, 60) || 'Generated image';
  // Switch the gallery to the Edit tab so the editor has its container.
  const modal = document.getElementById('gallery-modal');
  if (modal) {
    modal.querySelectorAll('.gallery-tab').forEach(t => t.classList.remove('active'));
    modal.querySelector('.gallery-tab[data-tab="editor"]')?.classList.add('active');
  }
  const imagesContainer = document.getElementById('gallery-images-container');
  const albumsContainer = document.getElementById('gallery-albums-container');
  const generateContainer = document.getElementById('gallery-generate-container');
  const editorContainer = document.getElementById('gallery-editor-container');
  if (imagesContainer) imagesContainer.style.display = 'none';
  if (albumsContainer) albumsContainer.style.display = 'none';
  if (generateContainer) generateContainer.style.display = 'none';
  if (editorContainer) editorContainer.style.display = 'flex';
  openEditor(_lastResult.url, _lastResult.image_id || null, null, label);
}

async function _onDiscard() {
  if (!_lastResult?.image_id) {
    _resetResult();
    return;
  }
  const ok = await uiModule.styledConfirm('Discard this generated image?', {
    confirmText: 'Discard', danger: true,
  });
  if (!ok) return;
  try {
    const res = await fetch(`${API_BASE}/api/gallery/${_lastResult.image_id}`, {
      method: 'DELETE',
      credentials: 'include',
    });
    if (res.ok) {
      uiModule.showToast('Image discarded');
      _resetResult();
      try { window.dispatchEvent(new CustomEvent('gallery-refresh', { detail: { source: 'discard' } })); } catch (_) {}
    } else {
      uiModule.showToast('Could not discard image');
    }
  } catch (e) {
    uiModule.showToast('Discard failed');
  }
}

function _resetResult() {
  _lastResult = null;
  const result = document.getElementById('gallery-gen-result');
  const empty = document.getElementById('gallery-gen-empty');
  const img = document.getElementById('gallery-gen-result-img');
  const meta = document.getElementById('gallery-gen-result-meta');
  const actions = document.getElementById('gallery-gen-result-actions');
  if (result) result.hidden = true;
  if (empty) empty.hidden = false;
  if (img) img.src = '';
  if (meta) meta.innerHTML = '';
  if (actions) actions.hidden = true;
}

/**
 * Open the gallery on the Generate tab. Used by the sidebar "+ new" button —
 * ensures the gallery modal is mounted, then activates the Generate tab.
 */
export async function openGenerateTab() {
  const { default: galleryMod } = await import('./gallery.js');
  galleryMod.openGallery();
  // Defer until the modal markup exists.
  requestAnimationFrame(() => {
    const tab = document.querySelector('#gallery-modal .gallery-tab[data-tab="generate"]');
    if (tab) tab.click();
  });
}

function _escHtml(s) {
  if (s == null) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

function _escAttr(s) {
  return _escHtml(s).replace(/"/g, '&quot;');
}

const galleryGenerateModule = {
  renderGenerateTab,
  refreshModels,
  openGenerateTab,
};

export default galleryGenerateModule;

// Wire the sidebar "+ new" button next to Gallery. The list-item itself opens
// the gallery modal (auto-wired by modalManager), so this button stops
// propagation and opens straight to the Generate tab instead.
if (typeof document !== 'undefined') {
  const _wireSidebarNew = () => {
    const btn = document.getElementById('gallery-generate-new-btn');
    if (!btn || btn.dataset.genWired === '1') return;
    btn.dataset.genWired = '1';
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openGenerateTab();
    });
  };
  // Module scripts are deferred, so the DOM is usually already parsed.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _wireSidebarNew, { once: true });
  } else {
    _wireSidebarNew();
  }
}
