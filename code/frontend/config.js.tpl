const CONFIG = {
  apiBaseUrl: "${api_base_url}",
  cognitoDomain: "${cognito_domain}",
  cognitoClientId: "${cognito_client_id}",
  cognitoRedirectUri: "${cognito_redirect_uri}",
  taskDefaultVcpu: ${task_default_vcpu},
  taskDefaultMemory: ${task_default_memory},
  taskMaxVcpu: ${task_max_vcpu},
  taskMaxMemory: ${task_max_memory},
  sessionIdleTimeoutMinutes: ${session_idle_timeout_minutes}
};

// context: "notebook" | "session" | null (no filter)
async function loadConfigurationOptions(selectEl, defaultValue, context) {
  selectEl.innerHTML = "";
  try {
    const res = await fetch(CONFIG.apiBaseUrl + "/api/configurations");
    if (res.ok) {
      const configs = await res.json();
      for (const cfg of configs) {
        if (context === "notebook" && cfg.validation_notebook_status === "FAILED") continue;
        if (context === "session" && cfg.validation_session_status === "FAILED") continue;
        const key = cfg.ecr_image_uri + "||" + cfg.iam_role_arn;
        const opt = document.createElement("option");
        opt.value = key;
        opt.dataset.ecrImageUri = cfg.ecr_image_uri;
        opt.dataset.iamRoleArn = cfg.iam_role_arn;
        opt.dataset.vcpu = cfg.vcpu || CONFIG.taskDefaultVcpu;
        opt.dataset.memory = cfg.memory || CONFIG.taskDefaultMemory;
        opt.textContent = cfg.name;
        selectEl.appendChild(opt);
      }
    }
  } catch (e) { /* ignore */ }
  if (defaultValue) selectEl.value = defaultValue;
}

function getSelectedConfig(selectEl) {
  const opt = selectEl.options[selectEl.selectedIndex];
  if (!opt) return { ecr_image_uri: "", iam_role_arn: "", vcpu: 0, memory: 0 };
  return {
    ecr_image_uri: opt.dataset.ecrImageUri,
    iam_role_arn: opt.dataset.iamRoleArn,
    vcpu: parseInt(opt.dataset.vcpu),
    memory: parseInt(opt.dataset.memory),
  };
}

// Fargate vCPU/memory constants and helpers
const VCPU_OPTIONS = [256, 512, 1024, 2048, 4096];
const MEMORY_BY_VCPU = {
  256: [512, 1024, 2048],
  512: [1024, 2048, 3072, 4096],
  1024: [2048, 3072, 4096, 5120, 6144, 7168, 8192],
  2048: [4096, 5120, 6144, 7168, 8192, 9216, 10240, 11264, 12288, 13312, 14336, 15360, 16384],
  4096: [8192, 9216, 10240, 11264, 12288, 13312, 14336, 15360, 16384, 17408, 18432, 19456, 20480, 21504, 22528, 23552, 24576, 25600, 26624, 27648, 28672, 29696, 30720],
};
function vcpuLabel(v) { v = parseInt(v); return v < 1024 ? (v / 1024).toFixed(2).replace(/0$/, "") + " vCPU" : (v / 1024) + " vCPU"; }
function memLabel(m) { m = parseInt(m); return m >= 1024 ? (m / 1024) + " GB" : m + " MB"; }

function populateVcpuSelect(sel, memSel, defaultVcpu, defaultMem) {
  sel.innerHTML = "";
  for (const v of VCPU_OPTIONS) {
    if (v > CONFIG.taskMaxVcpu) break;
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = vcpuLabel(v);
    if (v === (defaultVcpu || CONFIG.taskDefaultVcpu)) opt.selected = true;
    sel.appendChild(opt);
  }
  populateMemorySelect(sel, memSel, defaultMem);
}

function populateMemorySelect(vcpuSel, memSel, defaultMem) {
  const curVcpu = parseInt(vcpuSel.value);
  const allowed = (MEMORY_BY_VCPU[curVcpu] || []).filter(m => m <= CONFIG.taskMaxMemory);
  memSel.innerHTML = "";
  for (const m of allowed) {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = memLabel(m);
    if (m === (defaultMem || CONFIG.taskDefaultMemory)) opt.selected = true;
    memSel.appendChild(opt);
  }
}

function uptimeStr(iso) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return diff + "s";
  if (diff < 3600) return Math.floor(diff / 60) + "min";
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  return h + "h " + (m ? m + "min" : "");
}

function durationStr(startedAt, finishedAt) {
  if (!startedAt) return "-";
  const start = new Date(startedAt).getTime();
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  const s = Math.floor((end - start) / 1000);
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "min " + (s % 60) + "s";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h + "h " + (m ? m + "min" : "");
}

function applyNotebookDefaults(nb, cfgSel, vcpuSel, memSel) {
  if (nb.default_iam_role_arn && nb.default_ecr_image_uri) {
    cfgSel.value = nb.default_ecr_image_uri + "||" + nb.default_iam_role_arn;
  }
  if (nb.default_vcpu) { vcpuSel.value = nb.default_vcpu; populateMemorySelect(vcpuSel, memSel); }
  if (nb.default_memory) memSel.value = nb.default_memory;
}

function wireConfigSelects(configSel, vcpuSel, memSel) {
  function apply() {
    const cfg = getSelectedConfig(configSel);
    populateVcpuSelect(vcpuSel, memSel, cfg.vcpu, cfg.memory);
  }
  apply();
  configSel.addEventListener("change", apply);
  vcpuSel.addEventListener("change", function () { populateMemorySelect(vcpuSel, memSel); });
}

// --- Labels component ---

const LABEL_REGEX = /^[a-z\u00e0-\u00f6\u00f8-\u00ff0-9\-]+$/;

async function loadAllLabels() {
  try {
    const res = await fetch(CONFIG.apiBaseUrl + "/api/labels");
    if (res.ok) return await res.json();
  } catch (e) { /* ignore */ }
  return [];
}

function createLabelsInput(containerEl, allLabels) {
  let selected = [];
  containerEl.classList.add("labels-input");
  containerEl.innerHTML = '<div class="labels-pills"></div><input type="text" placeholder="Add label...">'
    + '<div class="labels-suggestions"></div>';
  var pillsEl = containerEl.querySelector(".labels-pills");
  var inputEl = containerEl.querySelector("input");
  var suggestEl = containerEl.querySelector(".labels-suggestions");

  function render() {
    pillsEl.innerHTML = "";
    for (var i = 0; i < selected.length; i++) {
      var pill = document.createElement("span");
      pill.className = "label-tag";
      pill.textContent = selected[i];
      var x = document.createElement("span");
      x.className = "remove-label";
      x.textContent = "\u00d7";
      x.dataset.idx = i;
      pill.appendChild(x);
      pillsEl.appendChild(pill);
    }
  }

  pillsEl.addEventListener("click", function (e) {
    if (!e.target.classList.contains("remove-label")) return;
    selected.splice(parseInt(e.target.dataset.idx), 1);
    render();
  });

  function showSuggestions(query) {
    var matches = allLabels.filter(function (l) {
      return l.indexOf(query) !== -1 && selected.indexOf(l) === -1;
    });
    if (matches.length === 0 || (!query && matches.length === allLabels.length)) {
      suggestEl.classList.remove("open");
      return;
    }
    suggestEl.innerHTML = "";
    for (var i = 0; i < Math.min(matches.length, 10); i++) {
      var d = document.createElement("div");
      d.textContent = matches[i];
      suggestEl.appendChild(d);
    }
    suggestEl.classList.add("open");
  }

  inputEl.addEventListener("input", function () {
    showSuggestions(inputEl.value.trim().toLowerCase());
  });

  inputEl.addEventListener("focus", function () {
    if (inputEl.value.trim()) showSuggestions(inputEl.value.trim().toLowerCase());
  });

  inputEl.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    var val = inputEl.value.trim().toLowerCase();
    if (!val || !LABEL_REGEX.test(val) || selected.indexOf(val) !== -1) return;
    selected.push(val);
    inputEl.value = "";
    suggestEl.classList.remove("open");
    render();
  });

  suggestEl.addEventListener("click", function (e) {
    var d = e.target.closest("div");
    if (!d) return;
    var val = d.textContent;
    if (selected.indexOf(val) === -1) selected.push(val);
    inputEl.value = "";
    suggestEl.classList.remove("open");
    render();
  });

  document.addEventListener("click", function (e) {
    if (!containerEl.contains(e.target)) suggestEl.classList.remove("open");
  });

  render();

  function flush() {
    var val = inputEl.value.trim().toLowerCase();
    if (val && LABEL_REGEX.test(val) && selected.indexOf(val) === -1) {
      selected.push(val);
      inputEl.value = "";
      suggestEl.classList.remove("open");
      render();
    }
  }

  return {
    getLabels: function () { flush(); return selected.slice(); },
    setLabels: function (arr) { selected = arr.slice(); render(); }
  };
}

function initMenuToggle(container) {
  container.addEventListener("click", function (e) {
    var toggle = e.target.closest(".menu-toggle");
    if (!toggle) return;
    e.stopPropagation();
    var menu = toggle.nextElementSibling;
    var wasOpen = menu.classList.contains("open");
    document.querySelectorAll(".menu-dropdown.open").forEach(function (m) { m.classList.remove("open"); });
    if (!wasOpen) menu.classList.add("open");
  });
  document.addEventListener("click", function () {
    document.querySelectorAll(".menu-dropdown.open").forEach(function (m) { m.classList.remove("open"); });
  });
}
