function readChecked() {
  if (typeof this.checked === "boolean") return this.checked;
  const checked = this.getAttribute && this.getAttribute("aria-checked");
  return checked === "true" ? true : checked === "false" ? false : null;
}
