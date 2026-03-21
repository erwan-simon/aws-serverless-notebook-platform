const CONFIG = {
  apiBaseUrl: "${api_base_url}",
  availableRoles: ${available_roles_json},
  availableImages: ${available_images_json},
  cognitoDomain: "${cognito_domain}",
  cognitoClientId: "${cognito_client_id}",
  cognitoRedirectUri: "${cognito_redirect_uri}",
  taskDefaultVcpu: ${task_default_vcpu},
  taskDefaultMemory: ${task_default_memory},
  taskMaxVcpu: ${task_max_vcpu},
  taskMaxMemory: ${task_max_memory},
  sessionIdleTimeoutMinutes: ${session_idle_timeout_minutes}
};

async function loadImageOptions(selectEl, defaultValue) {
  selectEl.innerHTML = "";
  const uris = new Set();
  for (const uri of CONFIG.availableImages) {
    uris.add(uri);
    const opt = document.createElement("option");
    opt.value = uri;
    opt.textContent = uri.split("/").pop();
    selectEl.appendChild(opt);
  }
  try {
    const res = await fetch(CONFIG.apiBaseUrl + "/api/images");
    if (res.ok) {
      const images = await res.json();
      for (const img of images) {
        if (!uris.has(img.ecr_image_uri)) {
          uris.add(img.ecr_image_uri);
          const opt = document.createElement("option");
          opt.value = img.ecr_image_uri;
          opt.textContent = img.name || img.ecr_image_uri.split("/").pop();
          selectEl.appendChild(opt);
        }
      }
    }
  } catch (e) { /* silently fall back to static list */ }
  if (defaultValue) selectEl.value = defaultValue;
}

async function loadRoleOptions(selectEl, defaultValue) {
  selectEl.innerHTML = "";
  const arns = new Set();
  for (const arn of CONFIG.availableRoles) {
    arns.add(arn);
    const opt = document.createElement("option");
    opt.value = arn;
    opt.textContent = arn.split("/").pop();
    selectEl.appendChild(opt);
  }
  try {
    const res = await fetch(CONFIG.apiBaseUrl + "/api/roles");
    if (res.ok) {
      const roles = await res.json();
      for (const role of roles) {
        if (!arns.has(role.iam_role_arn)) {
          arns.add(role.iam_role_arn);
          const opt = document.createElement("option");
          opt.value = role.iam_role_arn;
          opt.textContent = role.name || role.iam_role_arn.split("/").pop();
          selectEl.appendChild(opt);
        }
      }
    }
  } catch (e) { /* silently fall back to static list */ }
  if (defaultValue) selectEl.value = defaultValue;
}
