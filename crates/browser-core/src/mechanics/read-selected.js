function readSelected() {
  if (this.tagName === "SELECT") {
    const option = this.selectedOptions && this.selectedOptions[0];
    return option ? option.value + "\u0000" + (option.text || "") : null;
  }
  return (this.value || "") + "\u0000" + (this.innerText || "").trim();
}
