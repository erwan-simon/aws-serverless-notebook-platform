const CONFIG = {
  apiBaseUrl: "${api_base_url}",
  availableConfigurations: ${available_configurations_json},
  cognitoDomain: "${cognito_domain}",
  cognitoClientId: "${cognito_client_id}",
  cognitoRedirectUri: "${cognito_redirect_uri}",
  taskDefaultVcpu: ${task_default_vcpu},
  taskDefaultMemory: ${task_default_memory},
  taskMaxVcpu: ${task_max_vcpu},
  taskMaxMemory: ${task_max_memory},
  sessionIdleTimeoutMinutes: ${session_idle_timeout_minutes}
};

async function loadConfigurationOptions(selectEl, defaultValue) {
  selectEl.innerHTML = "";
  const seen = new Set();
  for (const cfg of CONFIG.availableConfigurations) {
    const key = cfg.ecr_image_uri + "||" + cfg.iam_role_arn;
    if (seen.has(key)) continue;
    seen.add(key);
    const opt = document.createElement("option");
    opt.value = key;
    opt.dataset.ecrImageUri = cfg.ecr_image_uri;
    opt.dataset.iamRoleArn = cfg.iam_role_arn;
    opt.dataset.vcpu = cfg.vcpu;
    opt.dataset.memory = cfg.memory;
    opt.textContent = cfg.name;
    selectEl.appendChild(opt);
  }
  try {
    const res = await fetch(CONFIG.apiBaseUrl + "/api/configurations");
    if (res.ok) {
      const configs = await res.json();
      for (const cfg of configs) {
        const key = cfg.ecr_image_uri + "||" + cfg.iam_role_arn;
        if (seen.has(key)) continue;
        seen.add(key);
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
  } catch (e) { /* silently fall back to static list */ }
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
