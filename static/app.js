const tableBody = document.querySelector("#perfume-table-body");
const statusEl = document.querySelector("#status");
const form = document.querySelector("#add-perfume-form");
const urlInput = document.querySelector("#perfume-url");

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

function formatPyramid(value) {
  if (!value) return "";

  try {
    const pyramid = typeof value === "string" ? JSON.parse(value) : value;
    const labels = [
      ["top_notes", "Top"],
      ["middle_notes", "Middle"],
      ["base_notes", "Base"],
    ];

    return labels
      .map(([key, label]) => {
        const notes = pyramid[key] || [];
        const names = notes.map((note) => note.name).filter(Boolean).join(", ");
        return names ? `${label}: ${names}` : "";
      })
      .filter(Boolean)
      .join("; ");
  } catch (error) {
    return value;
  }
}

function renderPerfumeRow(perfume) {
  const row = document.createElement("tr");
  row.dataset.id = perfume.id;

  const description = stripHtml(perfume.description).trim();
  const shortDescription = description.length > 220 ? `${description.slice(0, 220)}...` : description;
  const pyramid = formatPyramid(perfume.pyramid_data);

  row.innerHTML = `
    <td class="name-cell">${escapeHtml(perfume.name)}</td>
    <td>${escapeHtml(perfume.brand)}</td>
    <td class="pyramid-cell">${escapeHtml(pyramid)}</td>
    <td>
      <button class="like-button ${perfume.like ? "active" : ""}" type="button" aria-label="Toggle like">
        ${perfume.like ? "♥" : "♡"}
      </button>
    </td>
    <td class="description-cell">${escapeHtml(shortDescription)}</td>
    <td>${escapeHtml(perfume.creation_date)}</td>
    <td class="url-cell"><a href="${escapeHtml(perfume.original_address)}" target="_blank" rel="noreferrer">Open</a></td>
  `;

  const likeButton = row.querySelector(".like-button");
  likeButton.addEventListener("click", async () => {
    likeButton.disabled = true;
    try {
      const response = await fetch(`/perfume/${perfume.id}/like`, { method: "PUT" });
      const updated = await response.json();
      if (!response.ok) throw new Error(updated.error || "Could not update like status");

      perfume.like = updated.like;
      likeButton.classList.toggle("active", updated.like);
      likeButton.textContent = updated.like ? "♥" : "♡";
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      likeButton.disabled = false;
    }
  });

  return row;
}

function appendPerfume(perfume) {
  tableBody.appendChild(renderPerfumeRow(perfume));
}

async function loadPerfumes() {
  try {
    const response = await fetch("/get_all_perfume");
    const perfumes = await response.json();
    if (!response.ok) throw new Error(perfumes.error || "Could not load perfumes");

    tableBody.innerHTML = "";
    perfumes.forEach(appendPerfume);
    setStatus(perfumes.length ? `${perfumes.length} perfume entries loaded.` : "No perfumes saved yet.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const url = urlInput.value.trim();
  if (!url) return;

  const button = form.querySelector("button");
  button.disabled = true;
  urlInput.readOnly = true;
  setStatus("Fetching perfume data. This can take a moment...");

  try {
    const response = await fetch("/add_perfume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const perfume = await response.json();
    if (!response.ok) throw new Error(perfume.error || "Could not add perfume");

    appendPerfume(perfume);
    form.reset();
    urlInput.readOnly = false;
    setStatus(`Added ${perfume.name} by ${perfume.brand}.`);
  } catch (error) {
    urlInput.readOnly = false;
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});

loadPerfumes();
