/* Sorting and paging for complete, server-rendered collections (ADR 0007).
   Server-paged tables are not enhanced a second time. With no JavaScript,
   every row and its actions remain available, including one-time import results. */
(function () {
  "use strict";
  var collator = new Intl.Collator("id", { numeric: true, sensitivity: "base" });

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function readableText(node) {
    if (node.tagName === "TR") {
      return Array.from(node.cells).map(readableText).join(" ");
    }
    var copy = node.cloneNode(true);
    copy.querySelectorAll("dialog, button, .visually-hidden, input").forEach(function (child) {
      child.remove();
    });
    return copy.textContent.trim().replace(/\s+/g, " ");
  }

  function valueFor(cell, numeric) {
    var raw = cell.getAttribute("data-sort-value");
    if (raw !== null) {
      return raw === "" ? null : (numeric ? Number(raw) : raw);
    }
    var text = readableText(cell);
    if (!numeric) return text;
    // Indonesian formatting: 1.234,5 L. Missing measurements remain last.
    var match = text.match(/^-?\d[\d.]*(?:,\d+)?(?=\s|%|$)/);
    return match ? Number(match[0].replace(/\./g, "").replace(",", ".")) : null;
  }

  function compare(left, right, direction) {
    if (left === null || Number.isNaN(left)) return right === null || Number.isNaN(right) ? 0 : 1;
    if (right === null || Number.isNaN(right)) return -1;
    var order = typeof left === "number" ? left - right : collator.compare(left, right);
    return direction === "desc" ? -order : order;
  }

  function field(parent, label, control, id) {
    var wrapper = element("div", "field");
    var caption = element("label", "", label);
    caption.htmlFor = id;
    control.id = id;
    wrapper.append(caption, control);
    parent.append(wrapper);
  }

  function enhance(collection, index) {
    var isTable = collection.tagName === "TABLE";
    var body = isTable ? collection.tBodies[0] : collection;
    if (!body) return;
    var rows = Array.from(body.children);
    if (!rows.length) return;
    var name = collection.dataset.listLabel;
    var id = collection.id || "collection-" + index;
    collection.id = id;
    var anchor = isTable ? collection.closest(".table-wrap") || collection : collection;
    var toolbar = element("div", "listing-toolbar collection-toolbar");
    toolbar.setAttribute("role", "group");
    toolbar.setAttribute("aria-label", "Kontrol " + name);
    var search = element("input");
    search.type = "search";
    search.placeholder = "Cari dalam " + name.toLocaleLowerCase("id");
    search.setAttribute("aria-controls", id);
    field(toolbar, "Cari", search, id + "-search");
    var size = element("select");
    [5, 10, 20, 50].forEach(function (count) {
      size.add(new Option(count + " baris", String(count)));
    });
    field(toolbar, "Per halaman", size, id + "-size");

    var pager = element("nav", "pagination collection-pagination");
    pager.setAttribute("aria-label", "Halaman " + name);
    var status = element("p", "pagination__summary");
    status.id = id + "-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    var controls = element("div", "collection-pagination__buttons");
    var previous = element("button", "button button--secondary button--small", "‹ Sebelumnya");
    var next = element("button", "button button--secondary button--small", "Berikutnya ›");
    previous.type = next.type = "button";
    previous.setAttribute("aria-controls", id);
    next.setAttribute("aria-controls", id);
    var position = element("span", "hint");
    controls.append(previous, position, next);
    pager.append(status, controls);
    var empty = element("p", "empty-state", "Tidak ada hasil yang cocok. Coba kata lain.");
    empty.hidden = true;
    var page = 1;
    var sortKey = null;
    var direction = "asc";
    var headers = [];
    var records = rows.map(function (row, original) {
      return { row: row, original: original, search: readableText(row).toLocaleLowerCase("id"), values: {} };
    });

    if (isTable) {
      headers = Array.from(collection.tHead.rows[0].cells);
      collection.classList.add("table--sortable");
      headers.forEach(function (header, column) {
        var label = header.textContent.trim();
        var sortable = !header.hasAttribute("data-no-sort");
        var numeric = header.classList.contains("numeric");
        records.forEach(function (record) {
          var cell = record.row.cells[column];
          if (!cell) return;
          if (sortable) cell.dataset.label = label;
          record.values[column] = valueFor(cell, numeric);
        });
        if (!sortable) return;
        header.setAttribute("aria-sort", "none");
        var button = element("button", "collection-sort", label);
        button.type = "button";
        button.setAttribute("aria-label", "Urutkan " + label);
        button.addEventListener("click", function () {
          direction = sortKey === column ? (direction === "asc" ? "desc" : "asc") : (numeric ? "desc" : "asc");
          sortKey = column;
          page = 1;
          render();
        });
        header.replaceChildren(button);
      });
    } else {
      var sort = element("select");
      sort.add(new Option("Urutan awal", ""));
      (collection.dataset.listSort || "").split(",").filter(Boolean).forEach(function (definition) {
        var parts = definition.split(":");
        var key = parts[0];
        var label = parts[1];
        var type = parts[2] || "text";
        sort.add(new Option(label + (type === "text" ? " · A–Z" : " · terkecil / terlama"), key + ":asc"));
        sort.add(new Option(label + (type === "text" ? " · Z–A" : " · terbesar / terbaru"), key + ":desc"));
        records.forEach(function (record) {
          var raw = record.row.getAttribute("data-sort-" + key);
          record.values[key] = raw === null || raw === "" ? null : (type === "number" ? Number(raw) : raw);
        });
      });
      field(toolbar, "Urutkan", sort, id + "-sort");
      sort.addEventListener("change", function () {
        var selected = sort.value.split(":");
        sortKey = selected[0] || null;
        direction = selected[1];
        page = 1;
        render();
      });
    }

    function render() {
      var needle = search.value.trim().toLocaleLowerCase("id");
      var matched = records.filter(function (record) { return record.search.includes(needle); });
      if (sortKey !== null) {
        matched.sort(function (a, b) {
          return compare(a.values[sortKey], b.values[sortKey], direction) || a.original - b.original;
        });
      }
      var perPage = Number(size.value);
      var pages = Math.max(1, Math.ceil(matched.length / perPage));
      page = Math.min(page, pages);
      var start = (page - 1) * perPage;
      records.forEach(function (record) { record.row.hidden = true; });
      matched.forEach(function (record, i) {
        body.append(record.row);
        record.row.hidden = i < start || i >= start + perPage;
      });
      headers.forEach(function (header, column) {
        if (header.hasAttribute("aria-sort")) {
          header.setAttribute("aria-sort", column === sortKey ? (direction === "asc" ? "ascending" : "descending") : "none");
        }
      });
      status.textContent = "Menampilkan " + (matched.length ? start + 1 : 0) + "–" + Math.min(start + perPage, matched.length)
        + " dari " + matched.length + (needle ? " hasil pencarian" : " baris");
      position.textContent = "Halaman " + page + " dari " + pages;
      previous.disabled = page <= 1;
      next.disabled = page >= pages;
      empty.hidden = matched.length !== 0;
    }

    search.addEventListener("input", function () { page = 1; render(); });
    size.addEventListener("change", function () { page = 1; render(); });
    previous.addEventListener("click", function () { page -= 1; render(); });
    next.addEventListener("click", function () { page += 1; render(); });
    anchor.before(toolbar);
    anchor.after(empty, pager);
    render();
  }

  document.querySelectorAll("[data-list]").forEach(enhance);
})();
