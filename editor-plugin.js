/**
 * Docsify Editor Plugin
 * Редактирование wiki-файлов прямо из браузера.
 * Совместимость: Docsify 4+
 * Зависимости: marked.js (CDN)
 *
 * Подключение:
 *   <link rel="stylesheet" href="editor-plugin.css">
 *   <script src="editor-plugin.js"></script>
 */

;(function () {
  'use strict';

  /* =========================================
     Config
     ========================================= */
  var BACKEND_URL = window.location.protocol + '//' + window.location.hostname + ':8000';

  var DOMAINS = [
    { value: 'topics/gradostroitelstvo', label: 'Градостроительство' },
    { value: 'topics/zemelnoe-pravo',    label: 'Земельное право' },
    { value: 'topics/218-fz',            label: '218-ФЗ' },
    { value: 'topics/zhilishnoe-pravo',  label: 'Жилищное право' },
    { value: 'sources',                  label: 'Источники' }
  ];

  /* =========================================
     Utilities
     ========================================= */

  /**
   * Получить путь .md-файла из текущего hash Docsify.
   * #/topics/gradostroitelstvo/gpzu → topics/gradostroitelstvo/gpzu.md
   */
  function currentFilePath() {
    var hash = window.location.hash || '#/';
    var raw = hash.replace(/^#\/?/, '').replace(/\?.*$/, '');
    if (!raw || raw === '/') return 'README.md';
    // Remove trailing slash
    raw = raw.replace(/\/$/, '');
    // If already ends with .md, keep it
    if (/\.md$/i.test(raw)) return raw;
    return raw + '.md';
  }

  /** Today as YYYY-MM-DD */
  function todayISO() {
    var d = new Date();
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  /** Шаблон нового файла */
  function newFileTemplate(title) {
    return [
      '---',
      'title: ' + (title || ''),
      'type: тема',
      'status: draft',
      'date_added: ' + todayISO(),
      'tags: []',
      '---',
      '',
      '# ' + (title || ''),
      '',
      '## Нормативная основа',
      '',
      '',
      '## Ключевые позиции',
      '',
      '',
      '## Практические риски',
      '',
      '',
      '## Сводная таблица источников',
      '',
      '| Источник | Тип | Ключевой вывод |',
      '|----------|-----|----------------|',
      '|  |  |  |',
      ''
    ].join('\n');
  }

  /* --- DOM helpers --- */
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'className') { node.className = attrs[k]; }
        else if (k === 'textContent') { node.textContent = attrs[k]; }
        else if (k === 'innerHTML') { node.innerHTML = attrs[k]; }
        else if (k.indexOf('on') === 0) { node.addEventListener(k.slice(2).toLowerCase(), attrs[k]); }
        else { node.setAttribute(k, attrs[k]); }
      });
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (typeof c === 'string') node.appendChild(document.createTextNode(c));
        else if (c) node.appendChild(c);
      });
    }
    return node;
  }

  /* =========================================
     API
     ========================================= */
  var API = {
    read: function (path) {
      return fetch(BACKEND_URL + '/api/files/read?path=' + encodeURIComponent(path))
        .then(function (r) {
          if (!r.ok) throw new Error('Ошибка чтения: ' + r.status);
          return r.json();
        })
        .then(function (data) { return data.content; });
    },
    save: function (path, content) {
      return fetch(BACKEND_URL + '/api/files/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path, content: content })
      }).then(function (r) {
        if (!r.ok) throw new Error('Ошибка сохранения: ' + r.status);
        return r.json();
      });
    },
    delete: function (path) {
      return fetch(BACKEND_URL + '/api/files/delete?path=' + encodeURIComponent(path), {
        method: 'DELETE'
      }).then(function (r) {
        if (!r.ok) throw new Error('Ошибка удаления: ' + r.status);
        return r.json();
      });
    },
    tree: function () {
      return fetch(BACKEND_URL + '/api/files/tree')
        .then(function (r) {
          if (!r.ok) throw new Error('Ошибка получения дерева: ' + r.status);
          return r.json();
        });
    }
  };

  /* =========================================
     marked.js loader
     ========================================= */
  var markedReady = false;

  function ensureMarked(cb) {
    if (window.marked) { markedReady = true; cb(); return; }
    if (markedReady) { cb(); return; }
    var s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
    s.onload = function () { markedReady = true; cb(); };
    s.onerror = function () { console.error('Не удалось загрузить marked.js'); };
    document.head.appendChild(s);
  }

  function renderMarkdown(text) {
    if (!window.marked) return '<p style="color:#999;">Загрузка marked.js...</p>';
    // marked v4+ uses marked.parse; older versions use marked() directly
    var parse = window.marked.parse || window.marked;
    try { return parse(text); } catch (e) { return '<pre>' + text + '</pre>'; }
  }

  /* =========================================
     Toast Notifications
     ========================================= */
  var toastContainer = null;

  function showToast(msg, type) {
    if (!toastContainer) {
      toastContainer = el('div', { className: 'editor-toast-container' });
      document.body.appendChild(toastContainer);
    }
    var t = el('div', {
      className: 'editor-toast editor-toast-' + (type || 'info'),
      textContent: msg
    });
    toastContainer.appendChild(t);
    setTimeout(function () {
      t.style.transition = 'opacity 0.3s ease';
      t.style.opacity = '0';
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 300);
    }, 3000);
  }

  /* =========================================
     Delete Confirmation Modal
     ========================================= */
  function showDeleteModal(path, onConfirm) {
    var overlay = el('div', { className: 'editor-modal-overlay' });
    var modal = el('div', { className: 'editor-modal' }, [
      el('div', { className: 'editor-modal-title', innerHTML: '🗑️ Удаление файла' }),
      el('div', { className: 'editor-modal-body' }, [
        el('div', { className: 'editor-modal-warning', textContent: 'Это действие нельзя отменить. Файл будет удалён безвозвратно.' }),
        el('p', { textContent: 'Вы уверены, что хотите удалить файл?' }),
        el('p', { innerHTML: '<strong>' + path + '</strong>' })
      ]),
      el('div', { className: 'editor-modal-actions' }, [
        el('button', {
          className: 'editor-modal-btn editor-modal-btn-cancel',
          textContent: 'Отмена',
          onClick: function () { document.body.removeChild(overlay); }
        }),
        el('button', {
          className: 'editor-modal-btn editor-modal-btn-danger',
          textContent: '🗑️ Удалить',
          onClick: function () {
            document.body.removeChild(overlay);
            onConfirm();
          }
        })
      ])
    ]);
    overlay.appendChild(modal);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) document.body.removeChild(overlay);
    });
    document.body.appendChild(overlay);
  }

  /* =========================================
     Create File Modal
     ========================================= */
  function showCreateModal() {
    var overlay = el('div', { className: 'editor-modal-overlay' });

    var domainSelect = el('select', { className: 'editor-modal-select' });
    DOMAINS.forEach(function (d) {
      var opt = el('option', { value: d.value, textContent: d.label });
      domainSelect.appendChild(opt);
    });

    var slugInput = el('input', {
      className: 'editor-modal-input',
      type: 'text',
      placeholder: 'nazvanie-faila'
    });

    var previewPath = el('div', {
      className: 'editor-modal-hint',
      textContent: DOMAINS[0].value + '/.md'
    });

    function updatePreview() {
      var slug = slugInput.value.trim();
      previewPath.textContent = domainSelect.value + '/' + (slug || '') + '.md';
    }

    domainSelect.addEventListener('change', updatePreview);
    slugInput.addEventListener('input', updatePreview);

    var modal = el('div', { className: 'editor-modal' }, [
      el('div', { className: 'editor-modal-title', innerHTML: '➕ Создать файл' }),
      el('div', { className: 'editor-modal-body' }, [
        el('div', { className: 'editor-modal-field' }, [
          el('label', { className: 'editor-modal-label', textContent: 'Домен (раздел)' }),
          domainSelect
        ]),
        el('div', { className: 'editor-modal-field' }, [
          el('label', { className: 'editor-modal-label', textContent: 'Имя файла (slug, без .md)' }),
          slugInput,
          previewPath
        ])
      ]),
      el('div', { className: 'editor-modal-actions' }, [
        el('button', {
          className: 'editor-modal-btn editor-modal-btn-cancel',
          textContent: 'Отмена',
          onClick: function () { document.body.removeChild(overlay); }
        }),
        el('button', {
          className: 'editor-modal-btn editor-modal-btn-primary',
          textContent: '➕ Создать',
          onClick: function () {
            var slug = slugInput.value.trim();
            if (!slug) {
              slugInput.style.borderColor = '#e74c3c';
              slugInput.focus();
              return;
            }
            // Sanitize slug
            slug = slug.toLowerCase()
              .replace(/[^a-zа-яё0-9_-]/gi, '-')
              .replace(/-+/g, '-')
              .replace(/^-|-$/g, '');

            var fullPath = domainSelect.value + '/' + slug + '.md';
            var content = newFileTemplate(slug);

            document.body.removeChild(overlay);

            // Save then open in editor
            API.save(fullPath, content)
              .then(function () {
                showToast('Файл создан: ' + fullPath, 'success');
                openEditor(fullPath, content);
              })
              .catch(function (err) {
                showToast('Ошибка: ' + err.message, 'error');
              });
          }
        })
      ])
    ]);

    overlay.appendChild(modal);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) document.body.removeChild(overlay);
    });
    document.body.appendChild(overlay);

    setTimeout(function () { slugInput.focus(); }, 100);
  }

  /* =========================================
     Editor Overlay
     ========================================= */
  var editorOverlay = null;

  function openEditor(filePath, initialContent) {
    if (editorOverlay) return; // already open

    ensureMarked(function () {
      buildEditor(filePath, initialContent);
    });
  }

  function buildEditor(filePath, initialContent) {
    var originalContent = initialContent || '';
    var modified = false;

    /* --- Overlay --- */
    editorOverlay = el('div', { className: 'editor-overlay' });

    /* --- Top bar --- */
    var titleEl = el('span', { className: 'editor-topbar-title', textContent: '📝 ' + filePath });

    var saveBtn = el('button', {
      className: 'editor-topbar-btn editor-btn-save',
      innerHTML: '💾 Сохранить',
      onClick: doSave
    });

    var closeBtn = el('button', {
      className: 'editor-topbar-btn editor-btn-close',
      textContent: '✕ Закрыть',
      onClick: doClose
    });

    var topbar = el('div', { className: 'editor-topbar' }, [
      titleEl,
      el('div', { className: 'editor-topbar-actions' }, [saveBtn, closeBtn])
    ]);

    /* --- Textarea pane --- */
    var textarea = el('textarea', {
      className: 'editor-textarea',
      placeholder: 'Введите Markdown...',
      spellcheck: 'false'
    });
    textarea.value = originalContent;

    /* Tab support */
    textarea.addEventListener('keydown', function (e) {
      if (e.key === 'Tab') {
        e.preventDefault();
        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        var val = textarea.value;
        textarea.value = val.substring(0, start) + '  ' + val.substring(end);
        textarea.selectionStart = textarea.selectionEnd = start + 2;
        onInput();
      }
    });

    /* --- Preview pane --- */
    var previewEl = el('div', { className: 'editor-preview' });
    previewEl.innerHTML = renderMarkdown(originalContent);

    /* --- Status bar elements --- */
    var statusText = el('span', { className: 'editor-status-item editor-status-saved', textContent: '✓ Готово' });
    var lineCountEl = el('span', { className: 'editor-status-item' });
    var charCountEl = el('span', { className: 'editor-status-item' });

    function updateCounts() {
      var val = textarea.value;
      var lines = val.split('\n').length;
      lineCountEl.textContent = 'Строк: ' + lines;
      charCountEl.textContent = 'Символов: ' + val.length;
    }
    updateCounts();

    var statusbar = el('div', { className: 'editor-statusbar' }, [
      el('div', { className: 'editor-statusbar-left' }, [statusText]),
      el('div', { className: 'editor-statusbar-right' }, [lineCountEl, charCountEl])
    ]);

    /* --- Debounced preview update --- */
    var previewTimer = null;
    function onInput() {
      modified = true;
      statusText.className = 'editor-status-item editor-status-modified';
      statusText.textContent = '● Изменено';
      updateCounts();

      clearTimeout(previewTimer);
      previewTimer = setTimeout(function () {
        previewEl.innerHTML = renderMarkdown(textarea.value);
      }, 300);
    }

    textarea.addEventListener('input', onInput);

    /* --- Resize handle --- */
    var resizeHandle = el('div', { className: 'editor-resize-handle' });
    var editorPane = el('div', { className: 'editor-pane-editor' }, [
      el('div', { className: 'editor-pane-label', textContent: 'РЕДАКТОР' }),
      textarea
    ]);
    var previewPane = el('div', { className: 'editor-pane-preview' }, [
      el('div', { className: 'editor-pane-label', textContent: 'ПРЕДПРОСМОТР' }),
      previewEl
    ]);

    // Drag-resize
    (function () {
      var dragging = false;
      var startX, startEditorWidth, splitWidth;

      resizeHandle.addEventListener('mousedown', function (e) {
        dragging = true;
        startX = e.clientX;
        startEditorWidth = editorPane.offsetWidth;
        splitWidth = editorPane.parentNode.offsetWidth;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
      });

      document.addEventListener('mousemove', function (e) {
        if (!dragging) return;
        var dx = e.clientX - startX;
        var newW = startEditorWidth + dx;
        var minW = 200;
        var maxW = splitWidth - 200 - 6; // 6 = handle width
        newW = Math.max(minW, Math.min(maxW, newW));
        var pct = (newW / splitWidth * 100).toFixed(2);
        editorPane.style.flex = 'none';
        editorPane.style.width = pct + '%';
        previewPane.style.flex = '1';
      });

      document.addEventListener('mouseup', function () {
        if (dragging) {
          dragging = false;
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
        }
      });
    })();

    var split = el('div', { className: 'editor-split' }, [editorPane, resizeHandle, previewPane]);

    /* --- Container --- */
    var container = el('div', { className: 'editor-container' }, [topbar, split, statusbar]);
    editorOverlay.appendChild(container);

    /* --- Click outside = close --- */
    editorOverlay.addEventListener('mousedown', function (e) {
      if (e.target === editorOverlay) doClose();
    });

    /* --- Save function --- */
    function doSave() {
      if (!modified) return;
      saveBtn.disabled = true;
      statusText.className = 'editor-status-item editor-status-saving';
      statusText.textContent = '⏳ Сохранение...';

      API.save(filePath, textarea.value)
        .then(function () {
          modified = false;
          originalContent = textarea.value;
          statusText.className = 'editor-status-item editor-status-saved';
          statusText.textContent = '✓ Сохранено';
          saveBtn.disabled = false;
          showToast('Файл сохранён', 'success');
        })
        .catch(function (err) {
          statusText.className = 'editor-status-item editor-status-error';
          statusText.textContent = '✗ Ошибка сохранения';
          saveBtn.disabled = false;
          showToast('Ошибка: ' + err.message, 'error');
        });
    }

    /* --- Close function --- */
    function doClose() {
      if (modified) {
        if (!confirm('Есть несохранённые изменения. Закрыть без сохранения?')) return;
      }
      if (editorOverlay && editorOverlay.parentNode) {
        editorOverlay.parentNode.removeChild(editorOverlay);
      }
      editorOverlay = null;
      // Reload page to reflect changes
      if (!modified && originalContent !== initialContent) {
        // Content was saved — force Docsify reload
        if (window.Docsify && window.Docsify.dom) {
          // Trigger re-render by navigating
          var currentHash = window.location.hash;
          window.location.hash = '';
          setTimeout(function () { window.location.hash = currentHash; }, 50);
        }
      }
    }

    /* --- Keyboard shortcuts --- */
    function onKeyDown(e) {
      if (!editorOverlay) {
        document.removeEventListener('keydown', onKeyDown);
        return;
      }
      // Ctrl+S / Cmd+S
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        doSave();
      }
      // Escape
      if (e.key === 'Escape') {
        e.preventDefault();
        doClose();
      }
    }
    document.addEventListener('keydown', onKeyDown);

    /* --- Mount --- */
    document.body.appendChild(editorOverlay);
    textarea.focus();
  }

  /* =========================================
     Floating Toolbar
     ========================================= */
  function createToolbar() {
    var toolbar = el('div', { className: 'editor-toolbar' });

    /* Edit button */
    var editBtn = el('button', {
      className: 'editor-toolbar-btn editor-btn-edit',
      innerHTML: '✏️',
      'data-tooltip': 'Редактировать',
      onClick: function () {
        var path = currentFilePath();
        editBtn.style.animation = 'editorPulse 0.3s ease';
        setTimeout(function () { editBtn.style.animation = ''; }, 300);

        API.read(path)
          .then(function (content) {
            openEditor(path, content);
          })
          .catch(function (err) {
            showToast('Ошибка загрузки: ' + err.message, 'error');
          });
      }
    });

    /* Delete button */
    var deleteBtn = el('button', {
      className: 'editor-toolbar-btn editor-btn-delete',
      innerHTML: '🗑️',
      'data-tooltip': 'Удалить',
      onClick: function () {
        var path = currentFilePath();
        showDeleteModal(path, function () {
          API.delete(path)
            .then(function () {
              showToast('Файл удалён: ' + path, 'success');
              // Navigate to root
              window.location.hash = '#/';
            })
            .catch(function (err) {
              showToast('Ошибка: ' + err.message, 'error');
            });
        });
      }
    });

    toolbar.appendChild(editBtn);
    toolbar.appendChild(deleteBtn);
    document.body.appendChild(toolbar);
  }

  /* =========================================
     Sidebar "Create File" Button
     ========================================= */
  function injectSidebarButton() {
    var sidebar = document.querySelector('.sidebar-nav') ||
                  document.querySelector('aside.sidebar') ||
                  document.querySelector('.sidebar');
    if (!sidebar) return;

    // Avoid duplicate
    if (sidebar.querySelector('.editor-sidebar-create')) return;

    var btn = el('button', {
      className: 'editor-sidebar-create',
      innerHTML: '➕ Создать файл',
      onClick: function () { showCreateModal(); }
    });

    // Insert at the top of sidebar
    if (sidebar.firstChild) {
      sidebar.insertBefore(btn, sidebar.firstChild);
    } else {
      sidebar.appendChild(btn);
    }
  }

  /* =========================================
     Docsify Plugin Registration
     ========================================= */
  function editorPlugin(hook, vm) {
    // After initial render — inject toolbar & sidebar button
    hook.ready(function () {
      createToolbar();
      injectSidebarButton();
    });

    // After each route change — re-inject sidebar button (Docsify may rebuild sidebar)
    hook.doneEach(function () {
      injectSidebarButton();
    });
  }

  // Register plugin
  window.$docsify = window.$docsify || {};
  window.$docsify.plugins = (window.$docsify.plugins || []).concat(editorPlugin);

})();
