(function initServiceDesignerViewport(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ServiceDesignerViewport = api;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const CANVAS_WIDTH = 1120;
  const CANVAS_HEIGHT = 700;
  const NODE_WIDTH = 218;
  const NODE_HEIGHT = 156;
  const MIN_ZOOM = 0.32;
  const MAX_ZOOM = 1.6;

  function finite(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, finite(value, minimum)));
  }

  function normalizeViewport(viewport = {}) {
    return {
      x: finite(viewport.x),
      y: finite(viewport.y),
      zoom: clamp(viewport.zoom ?? 1, MIN_ZOOM, MAX_ZOOM),
    };
  }

  function graphBounds(nodes = []) {
    const positioned = nodes.filter((node) => (
      Number.isFinite(Number(node?.x)) && Number.isFinite(Number(node?.y))
    ));
    if (!positioned.length) {
      return {
        left: 0,
        top: 0,
        right: CANVAS_WIDTH,
        bottom: CANVAS_HEIGHT,
        width: CANVAS_WIDTH,
        height: CANVAS_HEIGHT,
      };
    }
    const left = Math.min(...positioned.map((node) => Number(node.x)));
    const top = Math.min(...positioned.map((node) => Number(node.y)));
    const right = Math.max(
      ...positioned.map((node) => Number(node.x) + NODE_WIDTH),
    );
    const bottom = Math.max(
      ...positioned.map((node) => Number(node.y) + NODE_HEIGHT),
    );
    return {
      left,
      top,
      right,
      bottom,
      width: Math.max(1, right - left),
      height: Math.max(1, bottom - top),
    };
  }

  function fitViewport(nodes, viewportWidth, viewportHeight, options = {}) {
    const width = Math.max(1, finite(viewportWidth, 1));
    const height = Math.max(1, finite(viewportHeight, 1));
    const padding = Math.max(0, finite(options.padding, 44));
    const leftInset = Math.max(0, finite(options.leftInset));
    const rightInset = Math.max(0, finite(options.rightInset));
    const topInset = Math.max(0, finite(options.topInset));
    const bottomInset = Math.max(0, finite(options.bottomInset));
    const availableWidth = Math.max(
      1,
      width - leftInset - rightInset - padding * 2,
    );
    const availableHeight = Math.max(
      1,
      height - topInset - bottomInset - padding * 2,
    );
    const bounds = graphBounds(nodes);
    const zoom = clamp(
      Math.min(
        availableWidth / bounds.width,
        availableHeight / bounds.height,
        finite(options.maxFitZoom, 1.05),
      ),
      MIN_ZOOM,
      MAX_ZOOM,
    );
    const x = leftInset
      + padding
      + (availableWidth - bounds.width * zoom) / 2
      - bounds.left * zoom;
    const y = topInset
      + padding
      + (availableHeight - bounds.height * zoom) / 2
      - bounds.top * zoom;
    return {x, y, zoom};
  }

  function zoomAtPoint(viewport, pointX, pointY, requestedZoom) {
    const current = normalizeViewport(viewport);
    const zoom = clamp(requestedZoom, MIN_ZOOM, MAX_ZOOM);
    const x = finite(pointX);
    const y = finite(pointY);
    const worldX = (x - current.x) / current.zoom;
    const worldY = (y - current.y) / current.zoom;
    return {
      x: x - worldX * zoom,
      y: y - worldY * zoom,
      zoom,
    };
  }

  function panViewport(viewport, deltaX, deltaY) {
    const current = normalizeViewport(viewport);
    return {
      ...current,
      x: current.x + finite(deltaX),
      y: current.y + finite(deltaY),
    };
  }

  function visibleWorldRect(viewport, viewportWidth, viewportHeight) {
    const current = normalizeViewport(viewport);
    return {
      x: -current.x / current.zoom,
      y: -current.y / current.zoom,
      width: Math.max(0, finite(viewportWidth)) / current.zoom,
      height: Math.max(0, finite(viewportHeight)) / current.zoom,
    };
  }

  function centerOnWorldPoint(
    viewport,
    worldX,
    worldY,
    viewportWidth,
    viewportHeight,
  ) {
    const current = normalizeViewport(viewport);
    return {
      ...current,
      x: finite(viewportWidth) / 2 - finite(worldX) * current.zoom,
      y: finite(viewportHeight) / 2 - finite(worldY) * current.zoom,
    };
  }

  function ensureWorldRectVisible(
    viewport,
    worldRect,
    viewportWidth,
    viewportHeight,
    options = {},
  ) {
    const current = normalizeViewport(viewport);
    const width = Math.max(1, finite(viewportWidth, 1));
    const height = Math.max(1, finite(viewportHeight, 1));
    const padding = Math.max(0, finite(options.padding, 32));
    const left = Math.max(0, finite(options.leftInset)) + padding;
    const right = width
      - Math.max(0, finite(options.rightInset))
      - padding;
    const top = Math.max(0, finite(options.topInset)) + padding;
    const bottom = height
      - Math.max(0, finite(options.bottomInset))
      - padding;
    const rect = {
      x: finite(worldRect?.x),
      y: finite(worldRect?.y),
      width: Math.max(1, finite(worldRect?.width, NODE_WIDTH)),
      height: Math.max(1, finite(worldRect?.height, NODE_HEIGHT)),
    };
    const screen = {
      left: current.x + rect.x * current.zoom,
      right: current.x + (rect.x + rect.width) * current.zoom,
      top: current.y + rect.y * current.zoom,
      bottom: current.y + (rect.y + rect.height) * current.zoom,
    };
    let x = current.x;
    let y = current.y;

    if (screen.right - screen.left > right - left) {
      x += (left + right) / 2 - (screen.left + screen.right) / 2;
    } else if (screen.left < left) {
      x += left - screen.left;
    } else if (screen.right > right) {
      x -= screen.right - right;
    }

    if (screen.bottom - screen.top > bottom - top) {
      y += (top + bottom) / 2 - (screen.top + screen.bottom) / 2;
    } else if (screen.top < top) {
      y += top - screen.top;
    } else if (screen.bottom > bottom) {
      y -= screen.bottom - bottom;
    }

    return {...current, x, y};
  }

  return {
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    MAX_ZOOM,
    MIN_ZOOM,
    NODE_HEIGHT,
    NODE_WIDTH,
    centerOnWorldPoint,
    ensureWorldRectVisible,
    fitViewport,
    graphBounds,
    normalizeViewport,
    panViewport,
    visibleWorldRect,
    zoomAtPoint,
  };
}));
