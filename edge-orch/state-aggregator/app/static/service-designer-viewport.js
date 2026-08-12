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
  // A free canvas can spread nodes well beyond the initial 1120×700 guide.
  // Keep enough zoom-out range for "전체 보기" to recover those nodes.
  const MIN_ZOOM = 0.12;
  const MAX_ZOOM = 1.6;
  const GRID_SIZE = 24;
  const SNAP_TOLERANCE = 8;
  const AUTO_PAN_EDGE = 56;
  const AUTO_PAN_MAX_SPEED = 14;

  function finite(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, finite(value, minimum)));
  }

  function normalizeNodePosition(position = {}, fallback = {}) {
    return {
      x: finite(position.x, finite(fallback.x)),
      y: finite(position.y, finite(fallback.y)),
    };
  }

  function dragNodePosition(
    start = {},
    startPointer = {},
    pointer = {},
    startViewport = {},
    viewport = {},
  ) {
    const origin = normalizeNodePosition(start);
    const initial = normalizeViewport(startViewport);
    const current = normalizeViewport(viewport);
    return {
      x: origin.x + (
        finite(pointer.x) - finite(startPointer.x)
        - (current.x - initial.x)
      ) / current.zoom,
      y: origin.y + (
        finite(pointer.y) - finite(startPointer.y)
        - (current.y - initial.y)
      ) / current.zoom,
    };
  }

  function dragAutoPanDelta(pointer = {}, bounds = {}, options = {}) {
    const edge = Math.max(1, finite(options.edge, AUTO_PAN_EDGE));
    const maxSpeed = Math.max(
      0,
      finite(options.maxSpeed, AUTO_PAN_MAX_SPEED),
    );
    const left = finite(bounds.left);
    const top = finite(bounds.top);
    const right = finite(bounds.right, left);
    const bottom = finite(bounds.bottom, top);
    if (right <= left || bottom <= top || !maxSpeed) return {x: 0, y: 0};

    function axis(value, minimum, maximum) {
      if (value < minimum + edge) {
        return maxSpeed * clamp((minimum + edge - value) / edge, 0, 1);
      }
      if (value > maximum - edge) {
        return -maxSpeed * clamp((value - (maximum - edge)) / edge, 0, 1);
      }
      return 0;
    }

    return {
      x: axis(finite(pointer.x), left, right),
      y: axis(finite(pointer.y), top, bottom),
    };
  }

  function constrainNodePosition(start = {}, position = {}, enabled = true) {
    const origin = {
      x: finite(start.x),
      y: finite(start.y),
    };
    const next = {
      x: finite(position.x, origin.x),
      y: finite(position.y, origin.y),
    };
    if (!enabled) return {...next, lockedAxis: null};
    if (Math.abs(next.x - origin.x) >= Math.abs(next.y - origin.y)) {
      return {x: next.x, y: origin.y, lockedAxis: "horizontal"};
    }
    return {x: origin.x, y: next.y, lockedAxis: "vertical"};
  }

  function nearestAlignment(
    coordinate,
    movingSize,
    nodes,
    axis,
    tolerance,
  ) {
    const movingAnchors = [
      {offset: movingSize / 2, rank: 0},
      {offset: 0, rank: 1},
      {offset: movingSize, rank: 1},
    ];
    const candidates = [];
    nodes.forEach((node) => {
      const targetCoordinate = finite(node?.[axis]);
      movingAnchors.forEach((anchor) => {
        const guide = targetCoordinate + anchor.offset;
        const delta = guide - (coordinate + anchor.offset);
        if (Math.abs(delta) > tolerance) return;
        candidates.push({
          coordinate: coordinate + delta,
          delta,
          guide,
          rank: anchor.rank,
        });
      });
    });
    candidates.sort((left, right) => (
      Math.abs(left.delta) - Math.abs(right.delta)
      || left.rank - right.rank
      || left.guide - right.guide
    ));
    return candidates[0] || null;
  }

  function snapNodePosition(
    position = {},
    nodes = [],
    movingNodeId = "",
    options = {},
  ) {
    const raw = {
      x: finite(position.x),
      y: finite(position.y),
    };
    const snapEnabled = options.snap !== false;
    const gridEnabled = snapEnabled && options.grid !== false;
    const guidesEnabled = snapEnabled && options.guides !== false;
    const tolerance = Math.max(
      0,
      finite(options.tolerance, SNAP_TOLERANCE),
    );
    const peers = nodes.filter((node) => String(node?.id) !== String(movingNodeId));
    const alignmentX = guidesEnabled && !options.lockX
      ? nearestAlignment(raw.x, NODE_WIDTH, peers, "x", tolerance)
      : null;
    const alignmentY = guidesEnabled && !options.lockY
      ? nearestAlignment(raw.y, NODE_HEIGHT, peers, "y", tolerance)
      : null;
    let x = raw.x;
    let y = raw.y;

    if (!options.lockX) {
      x = alignmentX
        ? alignmentX.coordinate
        : gridEnabled
          ? Math.round(raw.x / GRID_SIZE) * GRID_SIZE
          : raw.x;
    }
    if (!options.lockY) {
      y = alignmentY
        ? alignmentY.coordinate
        : gridEnabled
          ? Math.round(raw.y / GRID_SIZE) * GRID_SIZE
          : raw.y;
    }
    const placed = normalizeNodePosition({x, y}, raw);
    return {
      ...placed,
      guides: {
        vertical: alignmentX && placed.x === x ? alignmentX.guide : null,
        horizontal: alignmentY && placed.y === y ? alignmentY.guide : null,
      },
    };
  }

  function nudgeNodePosition(position = {}, key = "", accelerated = false) {
    const step = accelerated ? GRID_SIZE : 1;
    const delta = {
      ArrowLeft: {x: -step, y: 0},
      ArrowRight: {x: step, y: 0},
      ArrowUp: {x: 0, y: -step},
      ArrowDown: {x: 0, y: step},
    }[key];
    if (!delta) return normalizeNodePosition(position);
    return normalizeNodePosition({
      x: finite(position.x) + delta.x,
      y: finite(position.y) + delta.y,
    });
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

  function miniMapBounds(nodes = [], visibleRect = {}, padding = 80) {
    const graph = graphBounds(nodes);
    const visible = {
      left: finite(visibleRect.x),
      top: finite(visibleRect.y),
      right: finite(visibleRect.x) + Math.max(1, finite(visibleRect.width, 1)),
      bottom: finite(visibleRect.y) + Math.max(1, finite(visibleRect.height, 1)),
    };
    const safePadding = Math.max(0, finite(padding, 80));
    const left = Math.min(graph.left, visible.left) - safePadding;
    const top = Math.min(graph.top, visible.top) - safePadding;
    const right = Math.max(graph.right, visible.right) + safePadding;
    const bottom = Math.max(graph.bottom, visible.bottom) + safePadding;
    return {
      left,
      top,
      right,
      bottom,
      width: Math.max(1, right - left),
      height: Math.max(1, bottom - top),
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
    AUTO_PAN_EDGE,
    AUTO_PAN_MAX_SPEED,
    GRID_SIZE,
    MAX_ZOOM,
    MIN_ZOOM,
    NODE_HEIGHT,
    NODE_WIDTH,
    SNAP_TOLERANCE,
    centerOnWorldPoint,
    constrainNodePosition,
    dragAutoPanDelta,
    dragNodePosition,
    ensureWorldRectVisible,
    fitViewport,
    graphBounds,
    nudgeNodePosition,
    normalizeNodePosition,
    miniMapBounds,
    normalizeViewport,
    panViewport,
    snapNodePosition,
    visibleWorldRect,
    zoomAtPoint,
  };
}));
