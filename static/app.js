const tableBody = document.querySelector("#perfume-table-body");
const statusEl = document.querySelector("#status");
const form = document.querySelector("#add-perfume-form");
const urlInput = document.querySelector("#perfume-url");
const searchInput = document.querySelector("#table-search");
const sortableHeaders = document.querySelectorAll("th.sortable");
const currentPage = typeof PAGE === "string" ? PAGE : document.body.dataset.page || "library";
const isWishlistPage = currentPage === "wishlist";

const api = isWishlistPage
  ? {
    getAll: "/get_wishlist",
    add: "/add_to_wishlist",
    delete: (id) => `/wishlist/${id}`,
    move: (id) => `/wishlist/${id}/move`,
  }
  : {
    getAll: "/get_all_perfume",
    add: "/add_perfume",
    delete: (id) => `/perfume/${id}`,
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
    ["middle_notes", "Middle"],
    ["base_notes", "Base"],
  ];

  const levels = labels
    .map(([key, label]) => {
      const notes = pyramid[key] || [];
      const names = notes.map((note) => note.name).filter(Boolean).join(", ");
      if (!names) return "";

      return `
        <div class="pyramid-level">
          <span class="level-tag">${escapeHtml(label)}</span>
          <span>${escapeHtml(names)}</span>
        </div>
      `;
    })
    .filter(Boolean)
    .join("");

  return levels || `<span class="muted-text">No notes</span>`;
}

function pyramidSearchText(value) {
  const pyramid = parsePyramid(value);
  return ["top_notes", "middle_notes", "base_notes"]
    .flatMap((key) => pyramid[key] || [])
    .map((note) => note.name || "")
    .join(" ")
    .toLowerCase();
}

function autoResizeTextarea(textarea) {
  textarea.style.height = "auto";

  const cell = textarea.closest(".note-cell");
  const cellStyle = cell ? window.getComputedStyle(cell) : null;
  const cellHeight = cell ? cell.clientHeight : 0;
  const verticalPadding = cellStyle ? parseFloat(cellStyle.paddingTop) + parseFloat(cellStyle.paddingBottom) : 0;

  textarea.style.height = `${Math.max(textarea.scrollHeight, cellHeight - verticalPadding)}px`;
}

function autoResizeAllTextareas() {
  document.querySelectorAll(".note-input").forEach(autoResizeTextarea);
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
    indicator.textContent = isActive ? (currentSort.direction === "asc" ? "▲" : "▼") : "";
    header.setAttribute("aria-sort", isActive ? (currentSort.direction === "asc" ? "ascending" : "descending") : "none");
  });
}

function updatePerfumeInState(updated) {
  allPerfumes = allPerfumes.map((perfume) => (perfume.id === updated.id ? updated : perfume));
}

async function updateNote(perfume, textarea) {
  const note = textarea.value;
  if (note === textarea.dataset.originalValue) return;

  textarea.disabled = true;
  try {
    const response = await fetch(`/perfume/${perfume.id}/note`, {
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
    autoResizeTextarea(textarea);
    setStatus(error.message, true);
  } finally {
    textarea.disabled = false;
  }
}

async function updateSize(perfume, select) {
  const size = Number(select.value);
  select.disabled = true;

  try {
    const response = await fetch(`/perfume/${perfume.id}/size`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ size }),
    });
    const updated = await response.json();
    if (!response.ok) throw new Error(updated.error || "Could not update size");

    updatePerfumeInState(updated);
    setStatus(`Updated size for ${updated.name}.`);
  } catch (error) {
    select.value = String(perfume.size ?? 0);
    setStatus(error.message, true);
  } finally {
    select.disabled = false;
  }
}

async function deletePerfume(perfume, button) {
  const itemType = isWishlistPage ? "wishlist item" : "perfume";
  if (!window.confirm(`Delete ${perfume.name} by ${perfume.brand}?`)) return;

  button.disabled = true;
  try {
    const response = await fetch(api.delete(perfume.id), { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Could not delete ${itemType}`);

    allPerfumes = allPerfumes.filter((item) => item.id !== perfume.id);
    renderPerfumes();
    setStatus(`Deleted ${perfume.name} from ${isWishlistPage ? "wishlist" : "library"}.`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function moveToLibrary(perfume, button) {
  button.disabled = true;
  try {
    const response = await fetch(api.move(perfume.id), { method: "POST" });
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

  if (isWishlistPage) {
    row.innerHTML = `
      <td class="name-cell">${escapeHtml(perfume.name)}</td>
      <td class="brand-cell">${escapeHtml(perfume.brand)}</td>
      <td class="pyramid-cell"><div class="pyramid-levels">${renderPyramidHTML(perfume.pyramid_data)}</div></td>
      <td class="creation-cell">${escapeHtml(perfume.creation_date)}</td>
      <td class="url-cell"><a href="${escapeHtml(perfume.original_address)}" target="_blank" rel="noreferrer">Open</a></td>
      <td>
        <div class="action-cell">
          <button class="move-button" type="button">Move to Library</button>
          <button class="delete-button" type="button">Delete</button>
        </div>
      </td>
    `;

    const moveButton = row.querySelector(".move-button");
    moveButton.addEventListener("click", () => moveToLibrary(perfume, moveButton));

    const deleteButton = row.querySelector(".delete-button");
    deleteButton.addEventListener("click", () => deletePerfume(perfume, deleteButton));

    return row;
  }

  const note = stripHtml(perfume.description).trim();
  const size = Number(perfume.size ?? 0);

  row.innerHTML = `
    <td class="name-cell">${escapeHtml(perfume.name)}</td>
    <td class="brand-cell">${escapeHtml(perfume.brand)}</td>
    <td class="pyramid-cell"><div class="pyramid-levels">${renderPyramidHTML(perfume.pyramid_data)}</div></td>
    <td>
      <button class="like-button ${perfume.like ? "active" : ""}" type="button" aria-label="Toggle like">
        ${perfume.like ? "♥" : "♡"}
      </button>
    </td>
    <td class="note-cell">
      <select class="note-size-select" aria-label="Size for ${escapeHtml(perfume.name)}">
        ${Object.entries(sizeLabels)
      .map(([value, label]) => `<option value="${value}" ${Number(value) === size ? "selected" : ""}>${escapeHtml(label)}</option>`)
      .join("")}
      </select>
      <textarea class="note-input" rows="1" aria-label="Note for ${escapeHtml(perfume.name)}">${escapeHtml(note)}</textarea>
    </td>
    <td class="creation-cell">${escapeHtml(perfume.creation_date)}</td>
    <td class="url-cell"><a href="${escapeHtml(perfume.original_address)}" target="_blank" rel="noreferrer">Open</a></td>
    <td><button class="delete-button" type="button">Delete</button></td>
  `;

  const likeButton = row.querySelector(".like-button");
  likeButton.addEventListener("click", async () => {
    likeButton.disabled = true;
    try {
      const response = await fetch(`/perfume/${perfume.id}/like`, { method: "PUT" });
      const updated = await response.json();
      if (!response.ok) throw new Error(updated.error || "Could not update like status");

      updatePerfumeInState(updated);
      likeButton.classList.toggle("active", updated.like);
      likeButton.textContent = updated.like ? "♥" : "♡";
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      likeButton.disabled = false;
    }
  });

  const noteInput = row.querySelector(".note-input");
  noteInput.dataset.originalValue = note;
  requestAnimationFrame(() => autoResizeTextarea(noteInput));
  noteInput.addEventListener("input", () => autoResizeTextarea(noteInput));
  noteInput.addEventListener("blur", () => updateNote(perfume, noteInput));

  const sizeSelect = row.querySelector(".note-size-select");
  sizeSelect.addEventListener("change", () => updateSize(perfume, sizeSelect));

  const deleteButton = row.querySelector(".delete-button");
  deleteButton.addEventListener("click", () => deletePerfume(perfume, deleteButton));

  return row;
}

function renderPerfumes() {
  tableBody.innerHTML = "";
  const perfumes = sortedPerfumes();
  perfumes.forEach((perfume) => tableBody.appendChild(renderPerfumeRow(perfume)));
  updateSortIndicators();
  requestAnimationFrame(autoResizeAllTextareas);
}

async function loadPerfumes() {
  try {
    const response = await fetch(api.getAll);
    const perfumes = await response.json();
    if (!response.ok) throw new Error(perfumes.error || "Could not load perfumes");

    allPerfumes = perfumes;
    renderPerfumes();
    const label = isWishlistPage ? "wishlist" : "perfume";
    setStatus(perfumes.length ? `${perfumes.length} ${label} entries loaded.` : `No ${label} entries saved yet.`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

searchInput.addEventListener("input", () => {
  currentSearch = searchInput.value;
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
        const response = await fetch(api.add, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url }),
        });
        const perfume = await response.json();
        if (!response.ok) throw new Error(perfume.error || "Could not add perfume");

        added.push(perfume);
        allPerfumes = [perfume, ...allPerfumes];
        renderPerfumes();
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

window.addEventListener("resize", autoResizeAllTextareas);

loadPerfumes();
