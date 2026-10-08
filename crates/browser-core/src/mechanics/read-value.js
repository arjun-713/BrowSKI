function readValue() {
  if (this.isContentEditable) return String(this.innerText);
  return this.value !== undefined ? String(this.value) : null;
}
