const tableBody = document.querySelector("#perfume-table-body");
const statusEl = document.querySelector("#status");
const form = document.querySelector("#add-perfume-form");
const urlInput = document.querySelector("#perfume-url");
const searchInput = document.querySelector("#table-search");
const tableToolbar = document.querySelector(".table-toolbar");
const searchField = document.querySelector(".search-field");
const table = document.querySelector("table");
const tableWrap = document.querySelector(".table-wrap");
const tableHeaders = document.querySelectorAll("thead th");
const sortableHeaders = document.querySelectorAll("th.sortable");
const logoutLink = document.querySelector("#logout-link");
const currentPage = typeof PAGE === "string" ? PAGE : document.body.dataset.page || "library";
const isWishlistPage = currentPage === "wishlist";
const isArchivePage = currentPage === "archive";

const api = isWishlistPage
  ? {
    getAll: "/get_wishlist",
    add: "/add_to_wishlist",
    delete: (id) => `/wishlist/${id}`,
    details: (id) => `/wishlist/${id}/details`,
    move: (id) => `/wishlist/${id}/move`,
  }
  : {
    getAll: isArchivePage ? "/get_archived_perfumes" : "/get_all_perfume",
    add: "/add_perfume",
    delete: (id) => `/perfume/${id}`,
    details: (id) => `/perfume/${id}/details`,
  };

const sizeLabels = {
  0: "Sample",
  1: "Decant",
  2: "Full bottle",
  3: "Done",
};

let allPerfumes = [];
let currentSort = { column: "creation_date", direction: "desc" };
let currentSearch = "";
let editingPerfumeId = null;
let editingBackup = null;
const columnWidthsStorageKey = `fragrantica-column-widths-${currentPage}`;
let tableCols = [];

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function stripHtml(value) {
  const div = document.createElement("div");
  div.innerHTML = value || "";
  return div.textContent || div.innerText || "";
}

function parsePyramid(value) {
  if (!value) return {};

  try {
    return typeof value === "string" ? JSON.parse(value) : value;
  } catch (error) {
    return {};
  }
}

function renderPyramidHTML(value) {
  const pyramid = parsePyramid(value);
  const labels = [
    ["top_notes", "Top"],
    ["middle_notes", "Mid"],
    ["base_notes", "Base"],
  ];

  const levels = labels
    .map(([key, label]) => {
      const notes = pyramid[key] || [];
      if (!notes.length) return "";

      const rendered = [];
      notes.forEach((note, index) => {
        if (!note || !note.name) return;
        if (rendered.length) rendered.push(", ");
        rendered.push(renderNoteBadge(note));
      });
      if (!rendered.length) return "";

      return `
        <div class="pyramid-level">
          <span class="level-tag">${escapeHtml(label)}</span>
          <span class="notes-container">${rendered.join("")}</span>
        </div>
      `;
    })
    .filter(Boolean)
    .join("");

  return levels || `<span class="muted-text">No notes</span>`;
}

function renderNoteBadge(note) {
  const name = note.name || "";
  const odorProfile = (note.odor_profile || "").trim();
  const noteUrl = note.note_url || "";
  const imageUrl = note.image_url || "";
  const noteId = note.note_id || "";
  return `<span class="note-badge" data-note-id="${escapeHtml(noteId)}" data-note-name="${escapeHtml(name)}" data-odor-profile="${escapeHtml(odorProfile)}" data-note-url="${escapeHtml(noteUrl)}" data-note-image="${escapeHtml(imageUrl)}" tabindex="0" role="button" aria-label="View odor profile for ${escapeHtml(name)}">${escapeHtml(name)}</span>`;
}

function pyramidLevelText(value, key) {
  const pyramid = parsePyramid(value);
  return (pyramid[key] || [])
    .map((note) => note.name)
    .filter(Boolean)
    .join(", ");
}

function renderPyramidEditHTML(value) {
  return [
    ["top_notes", "Top"],
    ["middle_notes", "Mid"],
    ["base_notes", "Base"],
  ]
    .map(([key, label]) => `
      <label class="pyramid-edit-row">
        <span class="level-tag">${escapeHtml(label)}</span>
        <input class="edit-pyramid-input" data-key="${escapeHtml(key)}" type="text" value="${escapeHtml(pyramidLevelText(value, key))}" placeholder="${escapeHtml(label)} notes">
      </label>
    `)
    .join("");
}

function csvToNotes(value) {
  return String(value || "")
    .split(",")
    .map((note) => note.trim())
    .filter(Boolean)
    .map((name) => ({ name }));
}

function editedPyramidFromRow(row) {
  return ["top_notes", "middle_notes", "base_notes"].reduce((pyramid, key) => {
    const input = row.querySelector(`.edit-pyramid-input[data-key="${key}"]`);
    pyramid[key] = csvToNotes(input ? input.value : "");
    return pyramid;
  }, {});
}

function pyramidSearchText(value) {
  const pyramid = parsePyramid(value);
  return ["top_notes", "middle_notes", "base_notes"]
    .flatMap((key) => pyramid[key] || [])
    .map((note) => note.name || "")
    .join(" ")
    .toLowerCase();
}

function syncNoteInputMirror(textarea) {
  const wrapper = textarea.closest(".note-input-wrap");
  if (wrapper) wrapper.dataset.replicatedValue = `${textarea.value} `;
}

function sanitizeUrlInput(value) {
  return String(value)
    .split(",")
    .map((url) => url.trim().replace(/^["'<]+|["'>]+$/g, ""))
    .filter(Boolean)
    .map((url) => (/^https?:\/\//i.test(url) ? url : `https://${url}`));
}

function isValidFragranticaUrl(value) {
  try {
    const parsed = new URL(value);
    const hostname = parsed.hostname.toLowerCase();
    return (
      ["http:", "https:"].includes(parsed.protocol) &&
      (hostname === "fragrantica.com" || hostname.endsWith(".fragrantica.com")) &&
      parsed.pathname.includes("/perfume/")
    );
  } catch (error) {
    return false;
  }
}

function filteredPerfumes() {
  const search = currentSearch.trim().toLowerCase();
  if (!search) return allPerfumes;

  return allPerfumes.filter((perfume) => {
    const haystack = [
      perfume.name || "",
      perfume.brand || "",
      stripHtml(perfume.description || ""),
      pyramidSearchText(perfume.pyramid_data),
    ]
      .join(" ")
      .toLowerCase();

    return haystack.includes(search);
  });
}

function sortedPerfumes() {
  const { column, direction } = currentSort;
  const multiplier = direction === "asc" ? 1 : -1;

  return filteredPerfumes().sort((a, b) => {
    const left = String(a[column] ?? "").toLowerCase();
    const right = String(b[column] ?? "").toLowerCase();
    const comparison = left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" });

    if (comparison !== 0) return comparison * multiplier;
    return (Number(b.id) - Number(a.id)) * (column === "creation_date" ? 1 : 0);
  });
}

function updateSortIndicators() {
  sortableHeaders.forEach((header) => {
    const indicator = header.querySelector(".sort-indicator");
    const isActive = header.dataset.sort === currentSort.column;
    indicator.innerHTML = `
      <span class="sort-arrow ${isActive && currentSort.direction === "asc" ? "active" : ""}">▲</span>
      <span class="sort-arrow ${isActive && currentSort.direction === "desc" ? "active" : ""}">▼</span>
    `;
    header.setAttribute("aria-sort", isActive ? (currentSort.direction === "asc" ? "ascending" : "descending") : "none");
  });
}

function updatePerfumeInState(updated) {
  allPerfumes = allPerfumes.map((perfume) => (perfume.id === updated.id ? updated : perfume));
}

function columnMinWidth(header) {
  const label = header.textContent.trim().toLowerCase();
  const column = header.dataset.sort || label;

  if (column === "name") return 140;
  if (column === "brand") return 120;
  if (column === "rating") return 152;
  if (label.startsWith("pyramid")) return 280;
  if (label.startsWith("notes")) return 220;
  if (label.startsWith("actions")) return isWishlistPage ? 268 : 136;

  return 96;
}

function columnDefaultWidth(header) {
  const label = header.textContent.trim().toLowerCase();
  const column = header.dataset.sort || label;

  if (column === "name") return 220;
  if (column === "brand") return 160;
  if (column === "rating") return 152;
  if (label.startsWith("pyramid")) return 360;
  if (label.startsWith("notes")) return 320;
  if (label.startsWith("actions")) return columnMinWidth(header);

  return columnMinWidth(header);
}

function columnWidthTotal(widths) {
  return widths.reduce((total, width) => total + width, 0);
}

function parentTableWidth() {
  return tableWrap ? tableWrap.getBoundingClientRect().width : columnWidthTotal(Array.from(tableHeaders, columnMinWidth));
}

function storedColumnWidths() {
  try {
    const parsed = JSON.parse(localStorage.getItem(columnWidthsStorageKey) || "null");
    if (!Array.isArray(parsed) || parsed.length !== tableHeaders.length) return null;
    const widths = parsed.map((width) => Number(width));
    return widths.every((width) => Number.isFinite(width) && width > 0) ? widths : null;
  } catch (error) {
    return null;
  }
}

function saveColumnWidths(widths) {
  try {
    localStorage.setItem(columnWidthsStorageKey, JSON.stringify(widths.map((width) => Math.round(width))));
  } catch (error) {
    // Ignore storage failures so resizing still works in restricted browsing modes.
  }
}

function fittedColumnWidths(sourceWidths, minWidths) {
  const minTotal = columnWidthTotal(minWidths);
  const targetWidth = Math.max(parentTableWidth(), minTotal);
  const extraSpace = targetWidth - minTotal;

  if (extraSpace <= 0) return minWidths.slice();

  const widths = sourceWidths.map((width, index) => Math.max(Number(width) || minWidths[index], minWidths[index]));
  let extraWeights = widths.map((width, index) => Math.max(0, width - minWidths[index]));
  let extraTotal = columnWidthTotal(extraWeights);

  if (extraTotal <= 0) {
    extraWeights = minWidths.map((width) => width);
    extraTotal = columnWidthTotal(extraWeights);
  }

  const fitted = minWidths.map((minWidth, index) => minWidth + ((extraWeights[index] / extraTotal) * extraSpace));
  fitted[fitted.length - 1] += targetWidth - columnWidthTotal(fitted);

  return fitted;
}

function ensureTableColGroup() {
  let colGroup = table.querySelector("colgroup");
  if (!colGroup) {
    colGroup = document.createElement("colgroup");
    table.insertBefore(colGroup, table.firstElementChild);
  }

  colGroup.innerHTML = "";
  tableCols = Array.from(tableHeaders, () => {
    const col = document.createElement("col");
    colGroup.appendChild(col);
    return col;
  });
}

function resizeColumnPair(widths, minWidths, leftIndex, delta) {
  const rightIndex = leftIndex + 1;
  const maxLeftGrowth = widths[rightIndex] - minWidths[rightIndex];
  const maxLeftShrink = widths[leftIndex] - minWidths[leftIndex];
  const appliedDelta = Math.min(maxLeftGrowth, Math.max(-maxLeftShrink, delta));

  widths[leftIndex] += appliedDelta;
  widths[rightIndex] -= appliedDelta;
}

function applyColumnWidths(widths) {
  const tableWidth = columnWidthTotal(widths);
  tableCols.forEach((col, index) => {
    col.style.width = `${widths[index]}px`;
  });
  table.style.width = `${tableWidth}px`;
  table.style.minWidth = `${tableWidth}px`;
}

function initializeColumnResize() {
  if (!table || !tableHeaders.length) return;

  ensureTableColGroup();

  const minWidths = Array.from(tableHeaders, columnMinWidth);
  const storedWidths = storedColumnWidths();
  const defaultWidths = Array.from(tableHeaders, columnDefaultWidth);
  const widths = fittedColumnWidths(storedWidths || defaultWidths, minWidths);

  applyColumnWidths(widths);

  tableHeaders.forEach((header, index) => {
    if (index === tableHeaders.length - 1) return;

    const handle = document.createElement("span");
    handle.className = "column-resize-handle";
    handle.setAttribute("aria-hidden", "true");
    header.appendChild(handle);

    handle.addEventListener("click", (event) => event.stopPropagation());
    handle.addEventListener("mousedown", (event) => {
      event.preventDefault();
      event.stopPropagation();

      const startX = event.clientX;
      const startWidths = widths.slice();

      function handleMouseMove(moveEvent) {
        const delta = moveEvent.clientX - startX;
        for (let i = 0; i < widths.length; i += 1) widths[i] = startWidths[i];
        resizeColumnPair(widths, minWidths, index, delta);
        applyColumnWidths(widths);
      }

      function handleMouseUp() {
        document.body.classList.remove("resizing-column");
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
        saveColumnWidths(widths);
      }

      document.body.classList.add("resizing-column");
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    });
  });

  window.addEventListener("resize", () => {
    const fittedWidths = fittedColumnWidths(widths, minWidths);
    for (let index = 0; index < widths.length; index += 1) widths[index] = fittedWidths[index];
    applyColumnWidths(widths);
  });
}

function clearEditingState() {
  editingPerfumeId = null;
  editingBackup = null;
  document.removeEventListener("click", handleOutsideEditClick);
}

function cancelEditing() {
  if (!editingPerfumeId) return;
  const backup = editingBackup;
  if (backup) {
    allPerfumes = allPerfumes.map((perfume) => (perfume.id === backup.id ? { ...perfume, ...backup } : perfume));
  }
  clearEditingState();
  renderPerfumes();
}

function handleOutsideEditClick(event) {
  if (!editingPerfumeId) return;
  const editingRow = tableBody.querySelector(`tr[data-id="${editingPerfumeId}"]`);
  if (editingRow && editingRow.contains(event.target)) return;
  cancelEditing();
}

function startEditing(perfume) {
  if (editingPerfumeId && editingPerfumeId !== perfume.id) {
    clearEditingState();
  }

  editingPerfumeId = perfume.id;
  editingBackup = {
    id: perfume.id,
    name: perfume.name,
    brand: perfume.brand,
    pyramid_data: perfume.pyramid_data,
  };
  renderPerfumes();
  document.addEventListener("click", handleOutsideEditClick);
}

async function saveDetails(perfume, row, button) {
  const nameInput = row.querySelector(".edit-name-input");
  const brandInput = row.querySelector(".edit-brand-input");
  const name = nameInput.value.trim();
  const brand = brandInput.value.trim();

  if (!name || !brand) {
    setStatus("Name and brand are required.", true);
    return;
  }

  row.querySelectorAll("input, button").forEach((control) => {
    control.disabled = true;
  });

  try {
    const response = await window.Auth.authFetch(api.details(perfume.id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        brand,
        pyramid_data: editedPyramidFromRow(row),
      }),
    });
    const updated = await response.json();
    if (!response.ok) throw new Error(updated.error || "Could not update perfume details");

    updatePerfumeInState(updated);
    clearEditingState();
    renderPerfumes();
    setStatus(`Updated ${updated.name} by ${updated.brand}.`);
  } catch (error) {
    row.querySelectorAll("input, button").forEach((control) => {
      control.disabled = false;
    });
    button.disabled = false;
    setStatus(error.message, true);
  }
}

function normalizedRating(value) {
  const rating = Number(value);
  if (!Number.isInteger(rating)) return 0;
  return Math.min(5, Math.max(0, rating));
}

function updateStarDisplay(container, rating) {
  const currentRating = normalizedRating(rating);
  container.dataset.rating = String(currentRating);
  container.setAttribute("aria-valuenow", String(currentRating));
  container.setAttribute("aria-label", `Rating ${currentRating} out of 5`);
  container.querySelectorAll(".rating-star").forEach((star) => {
    star.classList.toggle("active", Number(star.dataset.value) <= currentRating);
  });
}

async function updateNote(perfume, textarea) {
  const note = textarea.value;
  if (note === textarea.dataset.originalValue) return;

  textarea.disabled = true;
  try {
    const response = await window.Auth.authFetch(`/perfume/${perfume.id}/note`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    const updated = await response.json();
    if (!response.ok) throw new Error(updated.error || "Could not update note");

    textarea.dataset.originalValue = note;
    updatePerfumeInState(updated);
    setStatus(`Updated note for ${updated.name}.`);
  } catch (error) {
    textarea.value = textarea.dataset.originalValue;
    syncNoteInputMirror(textarea);
    setStatus(error.message, true);
  } finally {
    textarea.disabled = false;
  }
}

async function updateSize(perfume, select) {
  const size = Number(select.value);
  select.disabled = true;

  try {
    const response = await window.Auth.authFetch(`/perfume/${perfume.id}/size`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ size }),
    });
    const updated = await response.json();
    if (!response.ok) throw new Error(updated.error || "Could not update size");

    if (currentPage === "library" && Number(updated.size) === 3) {
      allPerfumes = allPerfumes.filter((item) => item.id !== updated.id);
      renderPerfumes();
      setStatus(`Moved ${updated.name} to archive.`);
    } else if (isArchivePage && Number(updated.size) !== 3) {
      allPerfumes = allPerfumes.filter((item) => item.id !== updated.id);
      renderPerfumes();
      setStatus(`Moved ${updated.name} back to library.`);
    } else {
      updatePerfumeInState(updated);
      setStatus(`Updated size for ${updated.name}.`);
    }
  } catch (error) {
    select.value = String(perfume.size ?? 0);
    setStatus(error.message, true);
  } finally {
    select.disabled = false;
  }
}

async function updateRating(perfume, container, rating) {
  const previousRating = normalizedRating(container.dataset.savedRating);
  const nextRating = normalizedRating(rating);
  if (nextRating === previousRating) return;

  container.classList.add("saving");
  container.setAttribute("aria-disabled", "true");
  updateStarDisplay(container, nextRating);

  try {
    const response = await window.Auth.authFetch(`/perfume/${perfume.id}/rating`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: nextRating }),
    });
    const updated = await response.json();
    if (!response.ok) throw new Error(updated.error || "Could not update rating");

    container.dataset.savedRating = String(updated.rating);
    updatePerfumeInState(updated);
    updateStarDisplay(container, updated.rating);
    setStatus(`Updated rating for ${updated.name}.`);
  } catch (error) {
    updateStarDisplay(container, previousRating);
    setStatus(error.message, true);
  } finally {
    container.classList.remove("saving");
    container.setAttribute("aria-disabled", "false");
  }
}

async function deletePerfume(perfume, button) {
  const itemType = isWishlistPage ? "wishlist item" : "perfume";
  if (!window.confirm(`Delete ${perfume.name} by ${perfume.brand}?`)) return;

  button.disabled = true;
  try {
    const response = await window.Auth.authFetch(api.delete(perfume.id), { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Could not delete ${itemType}`);

    allPerfumes = allPerfumes.filter((item) => item.id !== perfume.id);
    renderPerfumes();
    setStatus(`Deleted ${perfume.name} from ${isWishlistPage ? "wishlist" : isArchivePage ? "archive" : "library"}.`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function moveToLibrary(perfume, button) {
  button.disabled = true;
  try {
    const response = await window.Auth.authFetch(api.move(perfume.id), { method: "POST" });
    const moved = await response.json();
    if (!response.ok) throw new Error(moved.error || "Could not move wishlist item");

    allPerfumes = allPerfumes.filter((item) => item.id !== perfume.id);
    renderPerfumes();
    setStatus(`Moved ${moved.name} to library.`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderPerfumeRow(perfume) {
  const row = document.createElement("tr");
  row.dataset.id = perfume.id;
  const isEditing = editingPerfumeId === perfume.id;
  const nameCell = isEditing
    ? `<td class="name-cell"><input class="edit-text-input edit-name-input" type="text" value="${escapeHtml(perfume.name)}" aria-label="Perfume name"></td>`
    : `<td class="name-cell">${escapeHtml(perfume.name)}</td>`;
  const brandCell = isEditing
    ? `<td class="brand-cell"><input class="edit-text-input edit-brand-input" type="text" value="${escapeHtml(perfume.brand)}" aria-label="Brand"></td>`
    : `<td class="brand-cell">${escapeHtml(perfume.brand)}</td>`;
  const pyramidCell = isEditing
    ? `<td class="pyramid-cell"><div class="pyramid-edit-inputs">${renderPyramidEditHTML(perfume.pyramid_data)}</div></td>`
    : `<td class="pyramid-cell"><div class="pyramid-levels">${renderPyramidHTML(perfume.pyramid_data)}</div></td>`;
  const editButton = `<button class="edit-button ${isEditing ? "saving-state" : "edit-icon-button"}" type="button" aria-label="${isEditing ? "Save details" : "Edit details"}">${isEditing ? "Save" : ""}</button>`;

  if (isWishlistPage) {
    row.innerHTML = `
      ${nameCell}
      ${brandCell}
      ${pyramidCell}
      <td>
        <div class="action-cell">
            <button class="move-button" type="button">Move to Library</button>
            ${editButton}
            ${isEditing ? "" : `
            <a class="action-link" href="${escapeHtml(perfume.original_address)}" target="_blank" rel="noreferrer" aria-label="Open ${escapeHtml(perfume.name)} on Fragrantica">Open</a>
            <button class="delete-button" type="button">Delete</button>
          `}
        </div>
      </td>
    `;

    const editButtonEl = row.querySelector(".edit-button");
    editButtonEl.addEventListener("click", (event) => {
      event.stopPropagation();
      if (isEditing) {
        saveDetails(perfume, row, editButtonEl);
      } else {
        startEditing(perfume);
      }
    });

    if (isEditing) return row;

    const moveButton = row.querySelector(".move-button");
    moveButton.addEventListener("click", () => moveToLibrary(perfume, moveButton));

    const deleteButton = row.querySelector(".delete-button");
    deleteButton.addEventListener("click", () => deletePerfume(perfume, deleteButton));

    return row;
  }

  const note = stripHtml(perfume.description).trim();
  const size = Number(perfume.size ?? 0);
  const rating = normalizedRating(perfume.rating);

  row.innerHTML = `
    ${nameCell}
    ${brandCell}
    <td class="rating-cell">
      <div
        class="rating-stars ${isEditing ? "disabled" : ""}"
        role="slider"
        tabindex="${isEditing ? "-1" : "0"}"
        aria-valuemin="0"
        aria-valuemax="5"
        aria-valuenow="${rating}"
        aria-label="Rating ${rating} out of 5"
        aria-disabled="${isEditing ? "true" : "false"}"
        data-rating="${rating}"
        data-saved-rating="${rating}"
      >
        ${[1, 2, 3, 4, 5]
      .map((value) => `<span class="rating-star ${value <= rating ? "active" : ""}" data-value="${value}" aria-hidden="true">★</span>`)
      .join("")}
      </div>
    </td>
    ${pyramidCell}
    <td class="note-cell">
      <select class="note-size-select" aria-label="Size for ${escapeHtml(perfume.name)}" ${isEditing ? "disabled" : ""}>
        ${Object.entries(sizeLabels)
      .map(([value, label]) => `<option value="${value}" ${Number(value) === size ? "selected" : ""}>${escapeHtml(label)}</option>`)
      .join("")}
      </select>
    <div class="note-input-wrap" data-replicated-value="${escapeHtml(`${note} `)}">
        <textarea class="note-input" rows="1" aria-label="Note for ${escapeHtml(perfume.name)}" ${isEditing ? "disabled" : ""}>${escapeHtml(note)}</textarea>
      </div>
    </td>
    <td>
      <div class="action-cell">
        ${editButton}
        ${isEditing ? "" : `
          <a class="action-link" href="${escapeHtml(perfume.original_address)}" target="_blank" rel="noreferrer" aria-label="Open ${escapeHtml(perfume.name)} on Fragrantica">Open</a>
          <button class="delete-button" type="button">Delete</button>
        `}
      </div>
    </td>
  `;

  const editButtonEl = row.querySelector(".edit-button");
  editButtonEl.addEventListener("click", (event) => {
    event.stopPropagation();
    if (isEditing) {
      saveDetails(perfume, row, editButtonEl);
    } else {
      startEditing(perfume);
    }
  });

  const ratingStars = row.querySelector(".rating-stars");
  ratingStars.addEventListener("click", (event) => {
    if (ratingStars.classList.contains("saving") || ratingStars.classList.contains("disabled")) return;
    const star = event.target.closest(".rating-star");
    if (star) {
      updateRating(perfume, ratingStars, Number(star.dataset.value));
      return;
    }

    const firstStar = ratingStars.querySelector(".rating-star");
    if (firstStar && event.clientX < firstStar.getBoundingClientRect().left) {
      updateRating(perfume, ratingStars, 0);
    }
  });
  ratingStars.addEventListener("mouseover", (event) => {
    const star = event.target.closest(".rating-star");
    if (!star || ratingStars.classList.contains("saving") || ratingStars.classList.contains("disabled")) return;
    updateStarDisplay(ratingStars, Number(star.dataset.value));
  });
  ratingStars.addEventListener("mouseleave", () => {
    if (ratingStars.classList.contains("saving") || ratingStars.classList.contains("disabled")) return;
    updateStarDisplay(ratingStars, ratingStars.dataset.savedRating);
  });
  ratingStars.addEventListener("keydown", (event) => {
    if (ratingStars.classList.contains("saving") || ratingStars.classList.contains("disabled")) return;
    if (!["ArrowLeft", "ArrowDown", "ArrowRight", "ArrowUp"].includes(event.key)) return;

    event.preventDefault();
    const direction = ["ArrowLeft", "ArrowDown"].includes(event.key) ? -1 : 1;
    const nextRating = normalizedRating(Number(ratingStars.dataset.savedRating) + direction);
    updateRating(perfume, ratingStars, nextRating);
  });

  const noteInput = row.querySelector(".note-input");
  noteInput.dataset.originalValue = note;
  noteInput.addEventListener("input", () => syncNoteInputMirror(noteInput));
  noteInput.addEventListener("blur", () => updateNote(perfume, noteInput));

  const sizeSelect = row.querySelector(".note-size-select");
  sizeSelect.addEventListener("change", () => updateSize(perfume, sizeSelect));

  if (isEditing) return row;

  const deleteButton = row.querySelector(".delete-button");
  deleteButton.addEventListener("click", () => deletePerfume(perfume, deleteButton));

  return row;
}

function renderPerfumes() {
  tableBody.innerHTML = "";
  const perfumes = sortedPerfumes();
  perfumes.forEach((perfume) => tableBody.appendChild(renderPerfumeRow(perfume)));
  updateSortIndicators();
  if (editingPerfumeId) {
    requestAnimationFrame(() => tableBody.querySelector(`tr[data-id="${editingPerfumeId}"] .edit-name-input`)?.focus());
  }
}

const noteProfileCache = {};
const inFlightEnrichments = new Set();

function getNotePopover() {
  let popover = document.getElementById("note-popover");
  if (popover) return popover;
  popover = document.createElement("div");
  popover.id = "note-popover";
  popover.className = "note-popover";
  popover.setAttribute("role", "tooltip");
  popover.setAttribute("aria-hidden", "true");
  document.body.appendChild(popover);
  return popover;
}

function positionNotePopover(badge, popover) {
  const rect = badge.getBoundingClientRect();
  const popoverRect = popover.getBoundingClientRect();
  const top = window.scrollY + rect.bottom + 8;
  let left = window.scrollX + rect.left;
  const maxLeft = window.scrollX + window.innerWidth - popoverRect.width - 12;
  if (left > maxLeft) left = Math.max(window.scrollX + 12, maxLeft);
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function renderNotePopoverContent(name, profile, noteUrl, imageUrl) {
  const trimmed = (profile || "").trim();
  const profileHtml = trimmed
    ? `<p class="note-popover-profile">${escapeHtml(trimmed)}</p>`
    : `<p class="note-popover-profile note-popover-empty">No odor profile found.</p>`;
  const imageHtml = imageUrl
    ? `<img class="note-popover-image" src="${escapeHtml(imageUrl)}" alt="">`
    : "";

  return `
    <div class="note-popover-inner">
      ${imageHtml}
      <div class="note-popover-body">
        <h4 class="note-popover-title">${escapeHtml(name)}</h4>
        ${profileHtml}
      </div>
    </div>
  `;
}

function applyPopover(badge, profile) {
  const popover = getNotePopover();
  const name = badge.dataset.noteName || "";
  const noteUrl = badge.dataset.noteUrl || "";
  const imageUrl = badge.dataset.noteImage || "";
  popover.innerHTML = renderNotePopoverContent(name, profile, noteUrl, imageUrl);
  popover.classList.add("visible");
  popover.setAttribute("aria-hidden", "false");
  positionNotePopover(badge, popover);
}

function showNotePopover(badge) {
  const name = badge.dataset.noteName || "";
  const noteId = badge.dataset.noteId || "";
  const profile = (badge.dataset.odorProfile || "").trim();

  if (profile) {
    applyPopover(badge, profile);
    return;
  }

  if (noteId && Object.prototype.hasOwnProperty.call(noteProfileCache, noteId)) {
    applyPopover(badge, noteProfileCache[noteId] || "");
    return;
  }

  const popover = getNotePopover();
  popover.innerHTML = renderNotePopoverContent(name, "", "", badge.dataset.noteImage || "");
  popover.classList.add("visible");
  popover.setAttribute("aria-hidden", "false");
  positionNotePopover(badge, popover);

  if (!noteId || inFlightEnrichments.has(noteId)) return;

  inFlightEnrichments.add(noteId);
  window.Auth.authFetch("/enrich_note", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      note_id: noteId,
      note_name: name,
      note_url: badge.dataset.noteUrl || "",
    }),
  })
    .then((response) => response.json().catch(() => ({})).then((data) => ({ ok: response.ok, data })))
    .then(({ ok, data }) => {
      const fetched = ok && data && typeof data.odor_profile === "string" ? data.odor_profile : "";
      noteProfileCache[noteId] = fetched;
      badge.dataset.odorProfile = fetched;
      if (!document.body.contains(badge)) return;
      const popoverEl = document.getElementById("note-popover");
      if (!popoverEl || !popoverEl.classList.contains("visible")) return;
      applyPopover(badge, fetched);
    })
    .catch(() => {
      noteProfileCache[noteId] = "";
    })
    .finally(() => {
      inFlightEnrichments.delete(noteId);
    });
}

function hideNotePopover() {
  const popover = document.getElementById("note-popover");
  if (!popover) return;
  popover.classList.remove("visible");
  popover.setAttribute("aria-hidden", "true");
}

document.addEventListener("mouseover", (event) => {
  const badge = event.target.closest(".note-badge");
  if (badge) showNotePopover(badge);
});

document.addEventListener("mouseout", (event) => {
  const badge = event.target.closest(".note-badge");
  if (badge) hideNotePopover();
});

document.addEventListener("focusin", (event) => {
  const badge = event.target.closest(".note-badge");
  if (badge) showNotePopover(badge);
});

document.addEventListener("focusout", (event) => {
  const badge = event.target.closest(".note-badge");
  if (badge) hideNotePopover();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideNotePopover();
});

document.addEventListener("click", (event) => {
  const link = event.target.closest(".note-popover-link");
  if (link) return;
  const badge = event.target.closest(".note-badge");
  if (!badge) return;
  const noteUrl = badge.dataset.noteUrl || "";
  if (noteUrl) window.open(noteUrl, "_blank", "noopener,noreferrer");
});

async function loadPerfumes() {
  try {
    const response = await window.Auth.authFetch(api.getAll);
    const perfumes = await response.json();
    if (!response.ok) throw new Error(perfumes.error || "Could not load perfumes");

    allPerfumes = perfumes;
    renderPerfumes();
    const label = isWishlistPage ? "wishlist" : (isArchivePage ? "archive" : "perfume");
    setStatus(perfumes.length ? `${perfumes.length} ${label} entries loaded.` : `No ${label} entries saved yet.`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

searchInput.addEventListener("input", () => {
  currentSearch = searchInput.value;
  renderPerfumes();
});

tableToolbar.addEventListener("click", (event) => {
  if (searchField.contains(event.target)) return;
  currentSort = { column: "creation_date", direction: "desc" };
  renderPerfumes();
});

sortableHeaders.forEach((header) => {
  header.addEventListener("click", () => {
    const column = header.dataset.sort;
    const direction = currentSort.column === column && currentSort.direction === "asc" ? "desc" : "asc";
    currentSort = { column, direction };
    renderPerfumes();
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const urls = sanitizeUrlInput(urlInput.value);
  const invalidUrls = urls.filter((url) => !isValidFragranticaUrl(url));
  if (!urls.length) return;
  if (invalidUrls.length) {
    setStatus("Every URL must be a fragrantica.com perfume page.", true);
    return;
  }

  const button = form.querySelector("button");
  button.disabled = true;
  urlInput.readOnly = true;

  const added = [];
  const failures = [];

  try {
    for (const [index, url] of urls.entries()) {
      setStatus(`Fetching perfume data ${index + 1}/${urls.length}. This can take a moment...`);

      try {
        const response = await window.Auth.authFetch(api.add, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url }),
        });
        const perfume = await response.json();
        if (!response.ok) throw new Error(perfume.error || "Could not add perfume");

        added.push(perfume);
        const belongsOnPage = isWishlistPage
          ? true
          : isArchivePage ? Number(perfume.size) === 3 : Number(perfume.size) !== 3;
        if (belongsOnPage) {
          allPerfumes = [perfume, ...allPerfumes];
          renderPerfumes();
        }
      } catch (error) {
        failures.push({ url, message: error.message });
      }
    }

    if (added.length) form.reset();

    if (failures.length) {
      setStatus(`Added ${added.length}/${urls.length}. ${failures.length} failed: ${failures[0].message}`, true);
    } else if (added.length === 1) {
      setStatus(`Added ${added[0].name} by ${added[0].brand}${isWishlistPage ? " to wishlist" : ""}.`);
    } else {
      setStatus(`Added ${added.length} ${isWishlistPage ? "wishlist items" : "perfumes"}.`);
    }
  } finally {
    urlInput.readOnly = false;
    button.disabled = false;
  }
});

initializeColumnResize();

if (logoutLink) {
  logoutLink.addEventListener("click", (event) => {
    event.preventDefault();
    window.Auth.logout();
  });
}

(async function initialize() {
  if (await window.Auth.requireAuth()) {
    loadPerfumes();
  }
})();
