const copyButton = document.getElementById("copy");

copyButton?.addEventListener("click", async () => {
  const field = document.getElementById(copyButton.dataset.target);
  field.select();
  field.setSelectionRange(0, field.value.length);

  try {
    await navigator.clipboard.writeText(field.value);
  } catch {
    document.execCommand("copy");
  }

  const original = copyButton.textContent;
  copyButton.textContent = "Copied";
  setTimeout(() => {
    copyButton.textContent = original;
  }, 1500);
});

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});
