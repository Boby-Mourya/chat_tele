(() => {
  'use strict';
  const script = document.currentScript;
  if (!script || script.dataset.northstarMounted === 'true') return;
  script.dataset.northstarMounted = 'true';

  const agentId = script.dataset.agentId;
  if (!agentId || !/^[A-Za-z0-9_-]{3,80}$/.test(agentId)) {
    console.error('[Northstar AI] A valid data-agent-id is required.');
    return;
  }

  const platformOrigin = new URL(script.src, window.location.href).origin;
  const configuredSide = ['left', 'right'].includes(script.dataset.position) ? script.dataset.position : null;
  const configuredColor = /^#[0-9a-f]{6}$/i.test(script.dataset.color || '') ? script.dataset.color : null;

  const checkedJson = async (response, label) => {
    if (!response.ok) throw new Error(`${label} failed (${response.status})`);
    return response.json();
  };
  const safeImageSource = (value) => {
    if (typeof value !== 'string' || !value.trim()) return '';
    const candidate = value.trim();
    if (candidate.startsWith('data:image/')) return candidate;
    try {
      const parsed = new URL(candidate, platformOrigin);
      return parsed.protocol === 'https:' || parsed.origin === platformOrigin ? parsed.toString() : '';
    } catch {
      return '';
    }
  };

  const load = async () => {
    const bootstrap = await fetch(`${platformOrigin}/api/v1/widget/${encodeURIComponent(agentId)}/bootstrap`, {
      credentials: 'omit',
      headers: { Accept: 'application/json' },
      mode: 'cors',
      referrerPolicy: 'strict-origin-when-cross-origin',
    }).then((response) => checkedJson(response, 'Widget bootstrap'));
    if (!bootstrap || bootstrap.publicId !== agentId || typeof bootstrap.sessionEndpoint !== 'string') {
      throw new Error('Widget bootstrap was invalid.');
    }
    mount(bootstrap);
  };

  const mount = (bootstrap) => {
    const appearance = bootstrap.appearance && typeof bootstrap.appearance === 'object' ? bootstrap.appearance : {};
    const translations = appearance.translations && typeof appearance.translations === 'object' ? appearance.translations : {};
    const side = configuredSide || (appearance.position === 'bottom-left' ? 'left' : 'right');
    const color = configuredColor || (/^#[0-9a-f]{6}$/i.test(appearance.primaryColor || '') ? appearance.primaryColor : '#146cf6');
    const launcherStyle = ['spark', 'bubble', 'avatar'].includes(appearance.launcherStyle) ? appearance.launcherStyle : 'spark';
    const launcherIcon = safeImageSource(translations.launcherIcon);
    const fallbackAvatar = safeImageSource(translations.botAvatar) || (typeof bootstrap.avatar === 'string' && bootstrap.avatar.trim() ? bootstrap.avatar.trim() : 'N');
    const chatName = typeof appearance.widgetName === 'string' && appearance.widgetName.trim() ? appearance.widgetName.trim() : (typeof bootstrap.name === 'string' ? bootstrap.name : 'AI support');
    const numberInRange = (value, fallback, min, max) => Number.isFinite(Number(value)) ? Math.min(max, Math.max(min, Number(value))) : fallback;
    const widgetWidth = numberInRange(appearance.widgetWidth, 380, 320, 600);
    const widgetHeight = numberInRange(appearance.widgetHeight, 680, 480, 900);
    const pageMargin = numberInRange(appearance.pageMargin, 24, 8, 64);
    const cornerRadius = numberInRange(appearance.cornerRadius, 24, 0, 32);
    const zIndex = numberInRange(appearance.zIndex, 99999, 1, 2147483647);
    const shadow = appearance.elevatedShadow === false ? 'none' : '0 22px 70px rgba(15,29,55,.24)';
    const fontFamily = ['Inter', 'DM Sans', 'Manrope', 'System UI'].includes(appearance.fontFamily) ? appearance.fontFamily : 'Inter';

    const container = document.createElement('div');
    container.id = `northstar-widget-${agentId}`;
    container.style.cssText = `position:fixed;${side}:${pageMargin}px;bottom:${pageMargin}px;z-index:${zIndex};font-family:${fontFamily},system-ui,sans-serif`;

    const frame = document.createElement('iframe');
    frame.title = `Chat with ${chatName}`;
    frame.loading = 'lazy';
    frame.allow = 'clipboard-write; microphone';
    frame.referrerPolicy = 'strict-origin-when-cross-origin';
    frame.style.cssText = `display:none;width:min(${widgetWidth}px,calc(100vw - 32px));height:min(${widgetHeight}px,calc(100vh - 112px));border:0;border-radius:${cornerRadius}px;background:#fff;box-shadow:${shadow}`;

    const launcher = document.createElement('button');
    launcher.type = 'button';
    launcher.setAttribute('aria-label', `Open chat with ${chatName}`);
    launcher.setAttribute('aria-expanded', 'false');
    launcher.style.cssText = `float:${side};width:58px;height:58px;margin-top:12px;border:0;border-radius:19px;color:#fff;background:${color};box-shadow:0 12px 28px rgba(20,108,246,.28);cursor:pointer;font-size:25px;overflow:hidden`;
    const renderLauncher = (opening) => {
      launcher.replaceChildren();
      if (opening) {
        launcher.textContent = '\u00d7';
        return;
      }
      const imageSource = launcherIcon || (launcherStyle === 'avatar' ? safeImageSource(fallbackAvatar) : '');
      if (imageSource) {
        const image = document.createElement('img');
        image.src = imageSource;
        image.alt = '';
        image.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block';
        launcher.append(image);
        return;
      }
      launcher.textContent = launcherStyle === 'bubble' ? '\u25a4' : launcherStyle === 'avatar' ? String(fallbackAvatar).slice(0, 2) : '\u2726';
    };
    renderLauncher(false);
    let frameLoaded = false;
    launcher.addEventListener('click', () => {
      const opening = frame.style.display === 'none';
      if (opening && !frameLoaded) {
        frameLoaded = true;
        frame.src = `${platformOrigin}/widget/${encodeURIComponent(agentId)}`;
      }
      frame.style.display = opening ? 'block' : 'none';
      renderLauncher(opening);
      launcher.setAttribute('aria-label', opening ? 'Close chat' : `Open chat with ${chatName}`);
      launcher.setAttribute('aria-expanded', String(opening));
      if (opening) frame.focus();
    });

    const sessionUrl = new URL(bootstrap.sessionEndpoint, platformOrigin);
    if (sessionUrl.origin !== platformOrigin) throw new Error('Widget session endpoint was invalid.');
    const createSession = async () => {
      const pageUrl = new URL(window.location.href);
      const attribution = new URLSearchParams();
      ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'].forEach((key) => {
        const value = pageUrl.searchParams.get(key);
        if (value) attribution.set(key, value.slice(0, 500));
      });
      pageUrl.search = attribution.toString();
      pageUrl.hash = '';
      const session = await fetch(sessionUrl.toString(), {
        method: 'POST',
        credentials: 'omit',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        mode: 'cors',
        referrerPolicy: 'strict-origin-when-cross-origin',
        body: JSON.stringify({ visitorName: script.dataset.visitorName || undefined, visitorEmail: script.dataset.visitorEmail || undefined, pageUrl: pageUrl.toString(), visitorDetails: {
          phone: script.dataset.visitorPhone || null,
          referrer: document.referrer ? document.referrer.split('?')[0].split('#')[0].slice(0, 2048) : null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          language: navigator.language,
        } }),
      }).then((response) => checkedJson(response, 'Widget session'));
      if (!session || typeof session.conversationId !== 'string' || typeof session.sessionToken !== 'string') {
        throw new Error('Widget session was invalid.');
      }
      return session;
    };

    const postToFrame = (message) => {
      if (frame.contentWindow) frame.contentWindow.postMessage(message, platformOrigin);
    };
    let initialSessionPromise = null;
    const initialize = () => {
      if (!initialSessionPromise) {
        initialSessionPromise = createSession().catch((error) => {
          initialSessionPromise = null;
          throw error;
        });
      }
      initialSessionPromise
        .then((session) => postToFrame({ type: 'northstar:init', agentId, bootstrap, session }))
        .catch(() => postToFrame({ type: 'northstar:init-error', agentId, message: 'Unable to start this chat.' }));
    };
    const sessionFlights = new Map();
    const createRequestedSession = (requestId) => {
      const pending = sessionFlights.get(requestId) || createSession();
      sessionFlights.set(requestId, pending);
      pending
        .then((session) => postToFrame({ type: 'northstar:session', agentId, requestId, session }))
        .catch(() => postToFrame({ type: 'northstar:session-error', agentId, requestId, message: 'Unable to start a new conversation.' }))
        .finally(() => sessionFlights.delete(requestId));
    };

    window.addEventListener('message', (event) => {
      if (event.source !== frame.contentWindow || event.origin !== platformOrigin) return;
      const message = event.data;
      if (!message || message.agentId !== agentId) return;
      if (message.type === 'northstar:ready') {
        initialize();
        return;
      }
      if (message.type === 'northstar:session-request' && typeof message.requestId === 'string' && /^[A-Za-z0-9_-]{8,128}$/.test(message.requestId)) {
        createRequestedSession(message.requestId);
      }
    });

    container.append(frame, launcher);
    document.body.append(container);
    if (appearance.openOnPageLoad === true) launcher.click();
  };

  void load().catch((error) => {
    console.error('[Northstar AI] Unable to initialize the widget.', error instanceof Error ? error.message : 'Unknown error');
  });
})();
