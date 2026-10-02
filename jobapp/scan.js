// Runs inside each page/frame. Finds every fillable question, tags it with
// data-jobapp-id, and returns a description the Python side can answer.
(prefix) => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").replace(/\*\s*$/, "").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  };
  const textOf = (id) => {
    const el = id && document.getElementById(id);
    return el ? clean(el.innerText || el.textContent) : "";
  };

  const labelFor = (el) => {
    if (el.getAttribute("aria-labelledby")) {
      const t = el.getAttribute("aria-labelledby").split(/\s+/).map(textOf).join(" ");
      if (clean(t)) return clean(t);
    }
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && clean(l.innerText)) return clean(l.innerText);
    }
    const wrap = el.closest("label");
    if (wrap && clean(wrap.innerText)) return clean(wrap.innerText);
    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));
    // Nearest container with a label-ish element above the field.
    let node = el;
    for (let i = 0; i < 5 && node; i++) {
      node = node.parentElement;
      if (!node) break;
      const l = node.querySelector("label, legend, [class*='label' i], [class*='question' i]");
      if (l && !l.contains(el) && clean(l.innerText)) return clean(l.innerText);
    }
    return clean(el.getAttribute("title"));
  };

  const groupLabel = (el) => {
    const fs = el.closest("fieldset");
    if (fs) {
      const lg = fs.querySelector("legend");
      if (lg && clean(lg.innerText)) return clean(lg.innerText);
    }
    const rg = el.closest("[role='radiogroup'], [role='group']");
    if (rg) {
      const t = rg.getAttribute("aria-labelledby");
      if (t && textOf(t)) return textOf(t);
      if (rg.getAttribute("aria-label")) return clean(rg.getAttribute("aria-label"));
    }
    let node = el.parentElement;
    for (let i = 0; i < 6 && node; i++, node = node.parentElement) {
      const l = node.querySelector("label:not(:has(input)), legend, [class*='label' i], [class*='question' i]");
      if (l && !l.querySelector("input") && clean(l.innerText)) return clean(l.innerText);
    }
    return "";
  };

  let n = 0;
  const out = [];
  const tag = (el) => {
    const uid = `${prefix}-${n++}`;
    el.setAttribute("data-jobapp-id", uid);
    return uid;
  };
  const isRequired = (el) =>
    el.required || el.getAttribute("aria-required") === "true" || /\*/.test(labelFor(el) || "");

  const groups = {};
  document.querySelectorAll("input, textarea, select").forEach((el) => {
    const type = (el.getAttribute("type") || el.tagName).toLowerCase();
    if (["hidden", "submit", "button", "reset", "image", "search", "password"].includes(type)) return;
    if (el.disabled || el.readOnly) return;
    if (type !== "file" && !visible(el)) return;

    if (type === "radio" || type === "checkbox") {
      const key = `${type}:${el.name || el.id}`;
      (groups[key] = groups[key] || []).push(el);
      return;
    }

    let kind = el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea" : type;
    if (el.getAttribute("role") === "combobox" && el.tagName === "INPUT") kind = "combobox";
    if (!["text", "email", "tel", "url", "number", "date", "textarea", "select", "file", "combobox"].includes(kind)) kind = "text";

    const filled = kind === "file" ? el.files && el.files.length > 0
      : kind === "select" ? el.selectedIndex > 0 && clean(el.options[el.selectedIndex].text) !== ""
      : clean(el.value) !== "";
    const options = kind === "select" ? Array.from(el.options).map((o) => clean(o.text)).filter(Boolean) : [];

    out.push({
      uid: tag(el), kind, label: labelFor(el), name: el.name || el.id || "",
      placeholder: el.getAttribute("placeholder") || "", options, required: isRequired(el), filled,
    });
  });

  Object.values(groups).forEach((els) => {
    const type = els[0].type;
    const shown = els.filter(visible).length > 0 || els.some((e) => {
      const l = e.closest("label") || (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`));
      return l && visible(l);
    });
    if (!shown) return;
    if (type === "checkbox" && els.length === 1) {
      const el = els[0];
      out.push({ uid: tag(el), kind: "checkbox", label: labelFor(el), name: el.name || "",
        placeholder: "", options: [], required: el.required, filled: el.checked });
      return;
    }
    const uid = `${prefix}-${n++}`;
    els.forEach((e, i) => e.setAttribute("data-jobapp-id", `${uid}-opt${i}`));
    out.push({
      uid, kind: type === "radio" ? "radio" : "checkbox",
      label: groupLabel(els[0]), name: els[0].name || "",
      placeholder: "", options: els.map(labelFor), required: els.some((e) => e.required),
      filled: els.some((e) => e.checked),
    });
  });
  return out;
}
