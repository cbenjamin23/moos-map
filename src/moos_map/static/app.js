(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    sources: [],
    mode: null,
    firstCorner: null,
    requestedLayer: null,
    actualLayer: null,
    originMarker: null,
    previewLayer: null,
    latestPlan: null,
  };

  const defaults = {
    west: -71.092,
    south: 42.357,
    east: -71.083,
    north: 42.363,
    originLat: 42.36,
    originLon: -71.087,
  };

  const map = L.map("map", { zoomControl: true }).setView([42.36, -71.087], 15);
  L.control.scale({ imperial: false }).addTo(map);

  function createBoxOverlay(kind) {
    const element = document.createElement("div");
    element.className = `selection-box ${kind}`;
    map.getContainer().appendChild(element);
    return {
      element,
      bounds: null,
      setBounds(bounds) {
        this.bounds = L.latLngBounds(bounds);
        positionBoxOverlay(this);
      },
      getBounds() { return this.bounds; },
      remove() { this.element.remove(); },
    };
  }

  function positionBoxOverlay(overlay) {
    if (!overlay || !overlay.bounds) return;
    const northwest = map.latLngToContainerPoint(overlay.bounds.getNorthWest());
    const southeast = map.latLngToContainerPoint(overlay.bounds.getSouthEast());
    overlay.element.style.left = `${northwest.x}px`;
    overlay.element.style.top = `${northwest.y}px`;
    overlay.element.style.width = `${Math.max(1, southeast.x - northwest.x)}px`;
    overlay.element.style.height = `${Math.max(1, southeast.y - northwest.y)}px`;
  }

  function createOriginOverlay() {
    const element = document.createElement("div");
    element.className = "origin-dot";
    element.title = "MOOS mission origin";
    map.getContainer().appendChild(element);
    return {
      element,
      point: null,
      setLatLng(point) {
        this.point = L.latLng(point);
        positionOriginOverlay(this);
      },
      remove() { this.element.remove(); },
    };
  }

  function positionOriginOverlay(overlay) {
    if (!overlay || !overlay.point) return;
    const point = map.latLngToContainerPoint(overlay.point);
    overlay.element.style.left = `${point.x}px`;
    overlay.element.style.top = `${point.y}px`;
  }

  function positionSelectionOverlays() {
    positionBoxOverlay(state.requestedLayer);
    positionBoxOverlay(state.actualLayer);
    positionOriginOverlay(state.originMarker);
  }

  function number(id) {
    return Number($(id).value);
  }

  function setInput(id, value) {
    $(id).value = Number(value).toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
  }

  function selectedSource() {
    return state.sources.find((source) => source.id === $("source").value);
  }

  function setMode(mode) {
    state.mode = mode;
    state.firstCorner = null;
    $("set-origin").classList.toggle("active", mode === "origin");
    $("draw-bounds").classList.toggle("active", mode === "bounds");
    $("map-hint").textContent = mode === "origin"
      ? "Click once to place the MOOS mission origin."
      : mode === "bounds"
        ? "Click two opposite corners of the requested area."
        : "Choose a tool, then click the map.";
  }

  function drawRequested() {
    const bounds = [[number("south"), number("west")], [number("north"), number("east")]];
    if (!state.requestedLayer) state.requestedLayer = createBoxOverlay("requested");
    state.requestedLayer.setBounds(bounds);
  }

  function drawOrigin() {
    const point = [number("origin-lat"), number("origin-lon")];
    if (!state.originMarker) state.originMarker = createOriginOverlay();
    state.originMarker.setLatLng(point);
  }

  function redrawInputs() {
    const values = ["west", "south", "east", "north", "origin-lat", "origin-lon"]
      .map((id) => number(id));
    if (values.every(Number.isFinite)) {
      drawRequested();
      drawOrigin();
    }
  }

  function setPreview(source) {
    if (state.previewLayer) state.previewLayer.remove();
    if (!source || !source.url_template) return;
    state.previewLayer = L.tileLayer(source.url_template, {
      minZoom: source.min_zoom,
      maxZoom: 22,
      maxNativeZoom: source.max_zoom,
      attribution: source.attribution,
    }).addTo(map);
    state.previewLayer.bringToBack();
  }

  function configureSource() {
    const id = $("source").value;
    const source = selectedSource();
    $("custom-source-fields").classList.toggle("hidden", id !== "custom");
    $("mbtiles-fields").classList.toggle("hidden", id !== "mbtiles");
    $("url-template").required = id === "custom";
    $("mbtiles-path").required = id === "mbtiles";
    const maxZoom = source ? source.max_zoom : 30;
    $("zoom").max = String(maxZoom);
    if (number("zoom") > maxZoom) $("zoom").value = String(maxZoom);
    $("zoom-value").value = $("zoom").value;

    if (source) {
      const capability = source.export_allowed ? "Static export allowed." : "Preview only; export is disabled.";
      $("source-note").textContent = `${capability} ${source.coverage}. ${source.note}`;
      setPreview(source);
    } else if (id === "custom") {
      $("source-note").textContent = "Custom XYZ export requires your explicit permission acknowledgement.";
    } else {
      $("source-note").textContent = "Reads an existing local tile archive; preview is not shown on the map.";
    }
  }

  function payload() {
    return {
      bounds: {
        west: number("west"), south: number("south"),
        east: number("east"), north: number("north"),
      },
      origin: { latitude: number("origin-lat"), longitude: number("origin-lon") },
      zoom: number("zoom"),
      source_id: $("source").value,
      name: $("name").value,
      output_dir: $("output-dir").value,
      emit_moos: $("emit-moos").checked,
      force: $("force").checked,
      custom_url_template: $("source").value === "custom" ? $("url-template").value : null,
      accept_custom_source_terms: $("accept-terms").checked,
      mbtiles_path: $("source").value === "mbtiles" ? $("mbtiles-path").value : null,
    };
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((item) => item.msg).join("; ")
        : data.detail;
      throw new Error(data.error || detail || `Request failed (${response.status})`);
    }
    return data;
  }

  function drawActual(plan) {
    const b = plan.actual_bounds;
    if (!state.actualLayer) state.actualLayer = createBoxOverlay("actual");
    state.actualLayer.setBounds([[b.south, b.west], [b.north, b.east]]);
  }

  function planHtml(plan, build = null) {
    const warnings = plan.warnings.length
      ? `<ul class="warnings">${plan.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul>`
      : "";
    const success = build ? `<div class="success">Map built and verified successfully.</div>` : "";
    const paths = build ? `<ul class="paths">
      <li>TIFF: <code>${escapeHtml(build.tiff_path)}</code></li>
      <li>Info: <code>${escapeHtml(build.info_path)}</code></li>
      ${build.moos_path ? `<li>MOOS: <code>${escapeHtml(build.moos_path)}</code></li>` : ""}
      <li>${build.downloaded_tiles} downloaded, ${build.cache_hits} from cache</li>
    </ul>` : "";
    return `${success}<h2>${build ? "Build result" : "Tile-aligned plan"}</h2>
      <div class="metrics">
        <div class="metric"><span>Tiles</span><strong>${plan.tiles.count} (${plan.tiles.columns} × ${plan.tiles.rows})</strong></div>
        <div class="metric"><span>TIFF pixels</span><strong>${plan.pixel_width} × ${plan.pixel_height}</strong></div>
        <div class="metric"><span>Viewer size</span><strong>${formatMeters(plan.pmarineviewer_width_m)} × ${formatMeters(plan.pmarineviewer_height_m)}</strong></div>
        <div class="metric"><span>Resolution</span><strong>${plan.approximate_meters_per_pixel.toFixed(2)} m/px</strong></div>
        <div class="metric"><span>Image center local XY</span><strong>${plan.image_center_local_x_m.toFixed(1)}, ${plan.image_center_local_y_m.toFixed(1)} m</strong></div>
        <div class="metric"><span>Est. placement error</span><strong>${plan.estimated_max_requested_area_position_error_m.toFixed(1)} m requested / ${plan.estimated_max_pmarineviewer_position_error_m.toFixed(1)} m full</strong></div>
        <div class="metric"><span>Width expansion</span><strong>${plan.expansion_width_ratio.toFixed(2)}×</strong></div>
        <div class="metric"><span>Height expansion</span><strong>${plan.expansion_height_ratio.toFixed(2)}×</strong></div>
      </div>${warnings}${paths}`;
  }

  function formatMeters(value) {
    return value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${value.toFixed(0)} m`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    })[character]);
  }

  function showError(error) {
    $("result").innerHTML = `<div class="error"><strong>Could not continue.</strong><br>${escapeHtml(error.message)}</div>`;
  }

  async function inspectPlan() {
    const plan = await api("/api/plan", { method: "POST", body: JSON.stringify(payload()) });
    state.latestPlan = plan;
    drawActual(plan);
    $("result").innerHTML = planHtml(plan);
    return plan;
  }

  async function buildMap() {
    const button = $("build-button");
    button.disabled = true;
    button.textContent = "Building…";
    try {
      const result = await api("/api/build", { method: "POST", body: JSON.stringify(payload()) });
      state.latestPlan = result.plan;
      drawActual(result.plan);
      $("result").innerHTML = planHtml(result.plan, result);
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
      button.textContent = "Build map";
    }
  }

  async function loadSources() {
    const data = await api("/api/sources");
    state.sources = data.sources;
    const options = data.sources.map((source) =>
      `<option value="${source.id}">${escapeHtml(source.name)}</option>`
    );
    options.push('<option value="mbtiles">Local MBTiles archive</option>');
    options.push('<option value="custom">Custom authorized XYZ source</option>');
    $("source").innerHTML = options.join("");
    $("source").value = "usgs-imagery";
    configureSource();
  }

  map.on("click", (event) => {
    if (state.mode === "origin") {
      setInput("origin-lat", event.latlng.lat);
      setInput("origin-lon", event.latlng.lng);
      drawOrigin();
      setMode(null);
      return;
    }
    if (state.mode === "bounds") {
      if (!state.firstCorner) {
        state.firstCorner = event.latlng;
        $("map-hint").textContent = "Now click the opposite corner.";
        return;
      }
      const first = state.firstCorner;
      setInput("west", Math.min(first.lng, event.latlng.lng));
      setInput("east", Math.max(first.lng, event.latlng.lng));
      setInput("south", Math.min(first.lat, event.latlng.lat));
      setInput("north", Math.max(first.lat, event.latlng.lat));
      drawRequested();
      setMode(null);
    }
  });
  map.on("move zoom resize", positionSelectionOverlays);

  $("set-origin").addEventListener("click", () => setMode("origin"));
  $("draw-bounds").addEventListener("click", () => setMode("bounds"));
  $("fit-result").addEventListener("click", () => {
    const layer = state.actualLayer || state.requestedLayer;
    if (layer) map.fitBounds(layer.getBounds(), { padding: [30, 30] });
  });
  $("source").addEventListener("change", configureSource);
  $("zoom").addEventListener("input", () => { $("zoom-value").value = $("zoom").value; });
  ["west", "south", "east", "north", "origin-lat", "origin-lon"].forEach((id) =>
    $(id).addEventListener("change", redrawInputs)
  );
  $("map-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await inspectPlan(); } catch (error) { showError(error); }
  });
  $("build-button").addEventListener("click", buildMap);

  setInput("west", defaults.west);
  setInput("south", defaults.south);
  setInput("east", defaults.east);
  setInput("north", defaults.north);
  setInput("origin-lat", defaults.originLat);
  setInput("origin-lon", defaults.originLon);
  redrawInputs();
  map.fitBounds(state.requestedLayer.getBounds(), { padding: [45, 45] });
  loadSources().catch(showError);
})();
