(function () {
  "use strict";

  var FAV_KEY = "travel_favorites";
  var ITIN_KEY = "travel_daily_itinerary";

  function safeGet(key) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function safeSet(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      /* storage unavailable (private mode, quota, etc.) — fail silently */
    }
  }

  function getFavoriteIds() {
    return safeGet(FAV_KEY).map(function (x) { return x.id; });
  }

  function getFavorites() {
    return safeGet(FAV_KEY);
  }

  function getItinerary() {
    return safeGet(ITIN_KEY);
  }

  function toggleFavorite(attraction) {
    var list = safeGet(FAV_KEY);
    var idx = list.findIndex(function (x) { return x.id === attraction.id; });
    if (idx >= 0) {
      list.splice(idx, 1);
    } else {
      list.push({ id: attraction.id, name_zh: attraction.name_zh, region_label: attraction.region_label });
    }
    safeSet(FAV_KEY, list);
    refreshFavoriteButtons();
    return idx < 0;
  }

  function addToItinerary(attraction) {
    var list = safeGet(ITIN_KEY);
    if (list.some(function (x) { return x.id === attraction.id; })) return false;
    list.push({ id: attraction.id, name_zh: attraction.name_zh, region_label: attraction.region_label });
    safeSet(ITIN_KEY, list);
    renderDrawer();
    return true;
  }

  function removeFromItinerary(id) {
    var list = safeGet(ITIN_KEY).filter(function (x) { return x.id !== id; });
    safeSet(ITIN_KEY, list);
    renderDrawer();
  }

  function clearItinerary() {
    safeSet(ITIN_KEY, []);
    renderDrawer();
  }

  function escapeHtml(str) {
    return String(str == null ? "" : str).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function cardHTML(a) {
    var isFav = getFavoriteIds().indexOf(a.id) >= 0;
    var costLine = a.access
      ? escapeHtml(a.access.from) + " → " + escapeHtml(a.access.method) + "・約" + a.access.duration_min + "分・" + a.access.cost_jpy + "円"
      : "";
    return (
      '<div class="card" data-id="' + escapeHtml(a.id) + '">' +
        '<div class="thumb"><img src="' + escapeHtml(a.image_url || "/static/img/placeholder.svg") + '" alt="' + escapeHtml(a.name_zh) + '" loading="lazy"></div>' +
        '<div class="card-body">' +
          '<h3>' + escapeHtml(a.name_zh) + (a.is_remote_island ? " 🏝️" : "") + '</h3>' +
          '<div class="card-tags">' +
            '<span class="tag">' + escapeHtml(a.region_label || a.region) + '</span>' +
            (a.tags || []).slice(0, 3).map(function (t) { return '<span class="tag">' + escapeHtml(t) + '</span>'; }).join("") +
          '</div>' +
          '<p class="card-desc">' + escapeHtml(a.description) + '</p>' +
          (costLine ? '<div class="card-meta">' + costLine + '</div>' : "") +
          '<div class="card-actions">' +
            '<button class="icon-btn fav-btn' + (isFav ? " active" : "") + '" data-action="fav">' + (isFav ? "♥ 已收藏" : "♡ 收藏") + '</button>' +
            '<button class="icon-btn" data-action="add">+ 加入行程</button>' +
            (a.maps_url ? '<a class="icon-btn" href="' + escapeHtml(a.maps_url) + '" target="_blank" rel="noopener">📍 地圖</a>' : "") +
            (a.official_url ? '<a class="icon-btn" href="' + escapeHtml(a.official_url) + '" target="_blank" rel="noopener">🔗 官方網站</a>' : "") +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function refreshFavoriteButtons() {
    var favIds = getFavoriteIds();
    document.querySelectorAll(".card").forEach(function (card) {
      var id = card.getAttribute("data-id");
      var btn = card.querySelector('[data-action="fav"]');
      if (!btn) return;
      var isFav = favIds.indexOf(id) >= 0;
      btn.classList.toggle("active", isFav);
      btn.textContent = isFav ? "♥ 已收藏" : "♡ 收藏";
    });
  }

  function bindGridActions(grid, attractionsById) {
    grid.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-action]");
      if (!btn) return;
      var card = e.target.closest(".card");
      var id = card.getAttribute("data-id");
      var attraction = attractionsById[id];
      if (!attraction) return;
      if (btn.getAttribute("data-action") === "fav") {
        toggleFavorite(attraction);
      } else if (btn.getAttribute("data-action") === "add") {
        var added = addToItinerary(attraction);
        btn.textContent = added ? "已加入 ✓" : "+ 加入行程";
        if (added) setTimeout(function () { btn.textContent = "+ 加入行程"; }, 1500);
      }
    });
  }

  function renderGrid(grid, list) {
    list = list || [];
    var byId = {};
    list.forEach(function (a) { byId[a.id] = a; });
    if (list.length === 0) {
      grid.innerHTML = '<div class="empty-state">找不到符合條件的景點或美食，換個關鍵字試試看。</div>';
    } else {
      grid.innerHTML = list.map(cardHTML).join("");
    }
    bindGridActions(grid, byId);
  }

  function fetchAttractions(params) {
    var qs = new URLSearchParams(params).toString();
    return fetch("/api/attractions?" + qs).then(function (r) { return r.json(); });
  }

  function debounce(fn, wait) {
    var t;
    return function () {
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  function initExplorePage() {
    var grid = document.getElementById("attraction-grid");
    if (!grid) return;
    var qInput = document.getElementById("search-q");
    var regionSelect = document.getElementById("search-region");
    var categorySelect = document.getElementById("search-category");
    var islandCheckbox = document.getElementById("search-island");

    function runSearch() {
      grid.innerHTML = '<div class="empty-state">搜尋中…</div>';
      var params = {
        q: qInput ? qInput.value : "",
        region: regionSelect ? regionSelect.value : "",
        category: categorySelect ? categorySelect.value : "",
      };
      // Only send remote_island when checked — FastAPI's bool query param
      // rejects an empty string with 422, which used to crash renderGrid().
      if (islandCheckbox && islandCheckbox.checked) {
        params.remote_island = "true";
      }
      fetchAttractions(params)
        .then(function (data) {
          renderGrid(grid, data.results || []);
        })
        .catch(function () {
          grid.innerHTML = '<div class="empty-state">搜尋時發生問題，請稍後再試一次。</div>';
        });
    }

    var debounced = debounce(runSearch, 250);
    [qInput, regionSelect, categorySelect, islandCheckbox].forEach(function (el) {
      if (el) el.addEventListener("input", debounced);
    });

    runSearch();
  }

  function initFavoritesPage() {
    var grid = document.getElementById("favorite-grid");
    if (!grid) return;
    var favIds = getFavoriteIds();
    if (favIds.length === 0) {
      grid.innerHTML = '<div class="empty-state">還沒有收藏任何景點或美食，去<a href="/explore">探索景點</a>看看吧！</div>';
      return;
    }
    fetchAttractions({})
      .then(function (data) {
        var favSet = {};
        favIds.forEach(function (id) { favSet[id] = true; });
        renderGrid(grid, (data.results || []).filter(function (a) { return favSet[a.id]; }));
      })
      .catch(function () {
        grid.innerHTML = '<div class="empty-state">載入收藏時發生問題，請重新整理再試一次。</div>';
      });
  }

  function renderDrawer() {
    var drawer = document.getElementById("itinerary-drawer");
    if (!drawer) return;
    var list = getItinerary();
    var body = drawer.querySelector(".drawer-body");
    var count = drawer.querySelector(".drawer-count");
    if (count) count.textContent = list.length;

    if (list.length === 0) {
      body.innerHTML = '<div class="empty-state" style="padding:20px 0">還沒有加入任何景點，逛逛探索頁把喜歡的行程加進來吧！</div>';
    } else {
      body.innerHTML = list.map(function (item) {
        return (
          '<div class="drawer-item">' +
            '<span>' + escapeHtml(item.name_zh) + '</span>' +
            '<button data-remove="' + escapeHtml(item.id) + '">移除</button>' +
          '</div>'
        );
      }).join("");
      body.querySelectorAll("[data-remove]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          removeFromItinerary(btn.getAttribute("data-remove"));
        });
      });
    }
  }

  function initDrawer() {
    var drawer = document.getElementById("itinerary-drawer");
    if (!drawer) return;
    var header = drawer.querySelector(".drawer-header");
    header.addEventListener("click", function () {
      drawer.classList.toggle("collapsed");
    });
    var clearBtn = drawer.querySelector('[data-action="clear"]');
    if (clearBtn) {
      clearBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (window.confirm("確定要清空今日行程嗎？")) clearItinerary();
      });
    }
    renderDrawer();
  }

  window.TravelApp = {
    toggleFavorite: toggleFavorite,
    addToItinerary: addToItinerary,
    removeFromItinerary: removeFromItinerary,
    clearItinerary: clearItinerary,
    refreshFavoriteButtons: refreshFavoriteButtons,
    bindGridActions: bindGridActions,
    cardHTML: cardHTML,
    renderGrid: renderGrid,
    fetchAttractions: fetchAttractions,
    getFavoriteIds: getFavoriteIds,
  };

  document.addEventListener("DOMContentLoaded", function () {
    initDrawer();
    initExplorePage();
    initFavoritesPage();
    refreshFavoriteButtons();
  });
})();
