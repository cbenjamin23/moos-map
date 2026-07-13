(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    sources: [],
    bounds: null,
    plan: null,
    previewLayer: null,
    selectionLayer: null,
    originMarker: null,
    selecting: false,
    selectionStart: null,
    previousBounds: null,
    planTimer: null,
    planSequence: 0,
  };

  const map = L.map("map", {
    zoomControl: true,
    dragging: true,
    boxZoom: false,
    doubleClickZoom: false,
  }).setView([42.36, -71.087], 18);
  L.control.scale({ imperial: false }).addTo(map);

  function number(id) {
    const value = $(id).value.trim();
    return value === "" ? Number.NaN : Number(value);
  }

  function setNumber(id, value) {
    $(id).value = Number(value).toFixed(10).replace(/0+$/, "").replace(/\.$/, "");
  }

  function selectedSource() {
    return state.sources.find((source) => source.id === $("source").value);
  }

  function createBoxOverlay() {
    const element = document.createElement("div");
    element.className = "selection-box";
    element.hidden = true;
    map.getContainer().appendChild(element);
    return {
      element,
      bounds: null,
      setBounds(bounds) {
        this.bounds = L.latLngBounds(bounds);
        this.element.hidden = false;
        positionBoxOverlay(this);
      },
      hide() { this.element.hidden = true; },
    };
  }

  function positionBoxOverlay(overlay) {
    if (!overlay || !overlay.bounds || overlay.element.hidden) return;
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
    element.hidden = true;
    map.getContainer().appendChild(element);
    return {
      element,
      point: null,
      setLatLng(point) {
        this.point = L.latLng(point);
        this.element.hidden = false;
        positionOriginOverlay(this);
      },
      hide() { this.element.hidden = true; },
    };
  }

  function positionOriginOverlay(overlay) {
    if (!overlay || !overlay.point || overlay.element.hidden) return;
    const point = map.latLngToContainerPoint(overlay.point);
    overlay.element.style.left = `${point.x}px`;
    overlay.element.style.top = `${point.y}px`;
  }

  function positionOverlays() {
    positionBoxOverlay(state.selectionLayer);
    positionOriginOverlay(state.originMarker);
  }

  function leafletBoundsToObject(bounds) {
    return {
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
    };
  }

  function boundsCenter(bounds) {
    return {
      latitude: (bounds.south + bounds.north) / 2,
      longitude: (bounds.west + bounds.east) / 2,
    };
  }

  function updateCornerInputs() {
    const values = state.bounds || {};
    const fields = {
      north: "corner-north",
      west: "corner-west",
      south: "corner-south",
      east: "corner-east",
    };
    for (const [key, id] of Object.entries(fields)) {
      $(id).value = Number.isFinite(values[key]) ? values[key].toFixed(8) : "";
    }
    $("corner-error").hidden = true;
    $("corner-error").textContent = "";
  }

  function applyCornerInputs() {
    const values = {
      north: number("corner-north"),
      west: number("corner-west"),
      south: number("corner-south"),
      east: number("corner-east"),
    };
    if (Object.values(values).some((value) => !Number.isFinite(value))) return;

    let message = "";
    if (values.north > 85.05112878 || values.south < -85.05112878) {
      message = "Corner latitudes must stay within the Web Mercator map limits.";
    } else if (values.west < -180 || values.east > 180) {
      message = "Corner longitudes must be between −180 and 180.";
    } else if (values.north <= values.south) {
      message = "Top-left latitude must be north of bottom-right latitude.";
    } else if (values.west >= values.east) {
      message = "Top-left longitude must be west of bottom-right longitude.";
    }

    if (message) {
      $("corner-error").textContent = message;
      $("corner-error").hidden = false;
      return;
    }

    $("corner-error").hidden = true;
    finalizeSelection(values, { fit: true });
  }

  function updateOriginFromSelection() {
    if (!state.bounds) return;
    const center = boundsCenter(state.bounds);
    if ($("auto-origin").checked || !Number.isFinite(number("origin-lat"))) {
      setNumber("origin-lat", center.latitude);
      setNumber("origin-lon", center.longitude);
    }
    drawOrigin();
  }

  function drawOrigin() {
    const latitude = number("origin-lat");
    const longitude = number("origin-lon");
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      if (state.originMarker) state.originMarker.hide();
      return;
    }
    if (!state.originMarker) state.originMarker = createOriginOverlay();
    state.originMarker.setLatLng([latitude, longitude]);
  }

  function finalizeSelection(bounds, { fit = false } = {}) {
    state.bounds = bounds;
    state.plan = null;
    if (!state.selectionLayer) state.selectionLayer = createBoxOverlay();
    state.selectionLayer.element.classList.remove("drawing");
    state.selectionLayer.setBounds([
      [bounds.south, bounds.west],
      [bounds.north, bounds.east],
    ]);
    updateCornerInputs();
    updateOriginFromSelection();
    if (fit) {
      map.fitBounds(state.selectionLayer.bounds, { padding: [35, 35], maxZoom: 21 });
    }
    $("map-hint").textContent = "Click once to replace this region. Click-hold-drag pans.";
    schedulePlan(0);
  }

  function beginSelection(event) {
    state.selecting = true;
    map.getContainer().classList.add("selecting");
    state.previousBounds = state.bounds;
    state.bounds = null;
    state.plan = null;
    updateCornerInputs();
    $("build-button").disabled = true;
    state.selectionStart = event.latlng;
    if (!state.selectionLayer) state.selectionLayer = createBoxOverlay();
    state.selectionLayer.hide();
    state.selectionLayer.element.classList.add("drawing");
    if (state.originMarker) state.originMarker.hide();
    $("summary").innerHTML = emptySummary(
      "Choosing region…",
      "Move the pointer, then click the opposite corner.",
    );
    $("map-hint").textContent = "Move to the opposite corner and click. Click-hold-drag still pans.";
  }

  function updateSelection(event) {
    if (!state.selecting) return;
    state.selectionLayer.setBounds(L.latLngBounds(state.selectionStart, event.latlng));
  }

  function finishSelection(event) {
    const start = map.latLngToContainerPoint(state.selectionStart);
    const end = map.latLngToContainerPoint(event.latlng);
    if (Math.abs(end.x - start.x) < 8 || Math.abs(end.y - start.y) < 8) {
      $("map-hint").textContent = "Move farther from the first corner, then click again.";
      return;
    }

    state.selecting = false;
    map.getContainer().classList.remove("selecting");
    state.selectionLayer.element.classList.remove("drawing");
    finalizeSelection(
      leafletBoundsToObject(L.latLngBounds(state.selectionStart, event.latlng)),
    );
    state.selectionStart = null;
    state.previousBounds = null;
  }

  function handleMapClick(event) {
    if (state.selecting) finishSelection(event);
    else beginSelection(event);
  }

  function cancelSelection() {
    if (!state.selecting) return;
    state.selecting = false;
    map.getContainer().classList.remove("selecting");
    state.selectionStart = null;
    state.selectionLayer.element.classList.remove("drawing");
    if (state.previousBounds) {
      const previous = state.previousBounds;
      state.previousBounds = null;
      finalizeSelection(previous);
      return;
    }
    state.selectionLayer.hide();
    state.previousBounds = null;
    updateCornerInputs();
    $("summary").innerHTML = emptySummary(
      "No region selected",
      "Click one corner, move the pointer, then click the opposite corner.",
    );
    $("map-hint").textContent = "Click once to start a region. Click-hold-drag pans the map.";
  }

  function setPreview(source) {
    if (state.previewLayer) state.previewLayer.remove();
    state.previewLayer = null;
    if (!source || !source.url_template) return;
    state.previewLayer = L.tileLayer(source.url_template, {
      minZoom: source.min_zoom,
      maxZoom: 24,
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
      $("source-note").textContent = `${source.coverage}. Native zoom ${source.min_zoom}–${source.max_zoom}. ${source.note}`;
      setPreview(source);
    } else if (id === "custom") {
      $("source-note").textContent = "Enter an XYZ tile URL and confirm export access.";
      setPreview(null);
    } else {
      $("source-note").textContent = "Build from a local MBTiles archive. Browser preview is not shown.";
      setPreview(null);
    }
    schedulePlan();
  }

  function requestPayload() {
    if (!state.bounds) return null;
    return {
      bounds: state.bounds,
      origin: {
        latitude: number("origin-lat"),
        longitude: number("origin-lon"),
      },
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
    let response;
    try {
      response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
    } catch (cause) {
      throw new Error(
        "The local MOOS Map service is not running. Relaunch it with “moos-map ui”, then retry the selection.",
        { cause },
      );
    }
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map((item) => item.msg).join("; ")
        : data.detail;
      throw new Error(data.error || detail || `Request failed (${response.status})`);
    }
    return data;
  }

  function schedulePlan(delay = 180) {
    clearTimeout(state.planTimer);
    if (!state.bounds) return;
    state.planTimer = setTimeout(refreshSummary, delay);
  }

  function sourceSetupIncomplete() {
    return (
      ($("source").value === "custom" && !$("url-template").value.trim())
      || ($("source").value === "mbtiles" && !$("mbtiles-path").value.trim())
    );
  }

  async function refreshSummary() {
    const payload = requestPayload();
    if (!payload) return null;
    if (sourceSetupIncomplete()) {
      state.plan = null;
      $("build-button").disabled = true;
      $("summary").innerHTML = emptySummary("Source details needed", "Complete the source fields above.");
      return null;
    }

    const sequence = ++state.planSequence;
    $("summary").classList.add("loading");
    try {
      const plan = await api("/api/plan", { method: "POST", body: JSON.stringify(payload) });
      if (sequence !== state.planSequence) return null;
      state.plan = plan;
      $("summary").innerHTML = summaryHtml(plan);
      $("build-button").disabled = !plan.source.export_allowed;
      return plan;
    } catch (error) {
      if (sequence !== state.planSequence) return null;
      state.plan = null;
      $("build-button").disabled = true;
      showError(error);
      return null;
    } finally {
      if (sequence === state.planSequence) $("summary").classList.remove("loading");
    }
  }

  async function buildMap(event) {
    event.preventDefault();
    if (!state.bounds) return;
    const button = $("build-button");
    button.disabled = true;
    button.textContent = "Building exact crop…";
    try {
      const plan = state.plan || await refreshSummary();
      if (!plan) return;
      const result = await api("/api/build", {
        method: "POST",
        body: JSON.stringify(requestPayload()),
      });
      state.plan = result.plan;
      $("summary").innerHTML = summaryHtml(result.plan, result);
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = !state.plan || !state.plan.source.export_allowed;
      button.textContent = "Build exact crop";
    }
  }

  function summaryHtml(plan, build = null) {
    const warnings = plan.warnings.length
      ? `<ul class="warnings">${plan.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul>`
      : "";
    const success = build
      ? '<div class="success">Exact crop built and verified successfully.</div>'
      : "";
    const paths = build ? `<ul class="paths">
      <li>TIFF: <code>${escapeHtml(build.tiff_path)}</code></li>
      <li>Info: <code>${escapeHtml(build.info_path)}</code></li>
      ${build.moos_path ? `<li>MOOS: <code>${escapeHtml(build.moos_path)}</code></li>` : ""}
      <li>${build.downloaded_tiles} downloaded, ${build.cache_hits} from cache</li>
    </ul>` : "";
    return `${success}<div class="summary-metrics">
      ${metric("Exact TIFF crop", `${plan.pixel_width.toLocaleString()} × ${plan.pixel_height.toLocaleString()} px`, "The TIFF is resampled to the exact selected bounds; extra source-tile margins are discarded.")}
      ${metric("Source tiles", `${plan.tiles.count} (${plan.tiles.columns} × ${plan.tiles.rows})`, "These tiles are downloaded to cover the selection before exact cropping. They are cached for reuse.")}
      ${metric("Source resolution", `${plan.approximate_meters_per_pixel.toFixed(3)} m/px`, "Nominal Web Mercator ground resolution at the selected latitude and export zoom.")}
      ${metric("Ground area", `${formatMeters(plan.approximate_ground_width_m)} × ${formatMeters(plan.approximate_ground_height_m)}`, "Approximate geographic width and height of the exact selected bounds.")}
      ${metric("Viewer size", `${formatMeters(plan.pmarineviewer_width_m)} × ${formatMeters(plan.pmarineviewer_height_m)}`, "Dimensions current pMarineViewer is expected to assign to the image using its UTM corner calculation.")}
      ${metric("Display alignment", `${plan.estimated_max_requested_area_position_error_m.toFixed(1)} m max`, "Known pMarineViewer background-display limitation: sampled difference between true MOOS UTM coordinates and the viewer's affine image placement. It does not change mission navigation or local XY coordinates.")}
    </div>
    <p class="summary-bounds">W ${plan.actual_bounds.west.toFixed(8)} · S ${plan.actual_bounds.south.toFixed(8)} · E ${plan.actual_bounds.east.toFixed(8)} · N ${plan.actual_bounds.north.toFixed(8)}</p>
    ${warnings}${paths}`;
  }

  function metric(label, value, tip) {
    return `<div class="metric"><span>${label}<span class="info-icon" tabindex="0" data-tip="${escapeHtml(tip)}">i</span></span><strong>${value}</strong></div>`;
  }

  function emptySummary(title, description) {
    return `<div class="empty-state"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(description)}</span></div>`;
  }

  function showError(error) {
    $("summary").innerHTML = `<div class="error"><strong>Could not continue.</strong><br>${escapeHtml(error.message)}</div>`;
  }

  function formatMeters(value) {
    return value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${value.toFixed(0)} m`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    })[character]);
  }

  async function loadSources() {
    const data = await api("/api/sources");
    state.sources = data.sources;
    const options = data.sources.map((source) =>
      `<option value="${source.id}">${escapeHtml(source.name)}</option>`
    );
    options.push('<option value="mbtiles">Local MBTiles archive</option>');
    options.push('<option value="custom">Custom XYZ source</option>');
    $("source").innerHTML = options.join("");
    $("source").value = "google-satellite";
    configureSource();
  }

  map.on("click", handleMapClick);
  map.on("mousemove", updateSelection);
  map.on("move zoom resize", positionOverlays);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") cancelSelection();
  });

  $("source").addEventListener("change", configureSource);
  $("zoom").addEventListener("input", () => {
    $("zoom-value").value = $("zoom").value;
    schedulePlan();
  });
  $("url-template").addEventListener("change", () => {
    if ($("url-template").value.trim()) {
      setPreview({
        url_template: $("url-template").value.trim(), min_zoom: 0,
        max_zoom: number("zoom"), attribution: "Custom source",
      });
    }
    schedulePlan(0);
  });
  $("mbtiles-path").addEventListener("change", () => schedulePlan(0));
  $("accept-terms").addEventListener("change", () => schedulePlan(0));
  $("map-form").addEventListener("submit", buildMap);

  for (const id of ["corner-north", "corner-west", "corner-south", "corner-east"]) {
    $(id).addEventListener("change", applyCornerInputs);
  }
  $("auto-origin").addEventListener("change", () => {
    const automatic = $("auto-origin").checked;
    $("origin-lat").disabled = automatic;
    $("origin-lon").disabled = automatic;
    $("origin-fields").classList.toggle("hidden", automatic);
    if (automatic) updateOriginFromSelection();
    schedulePlan(0);
  });
  $("origin-lat").addEventListener("change", () => { drawOrigin(); schedulePlan(0); });
  $("origin-lon").addEventListener("change", () => { drawOrigin(); schedulePlan(0); });

  loadSources().catch(showError);
})();
