function selectMetadata(wanted, by) {
  const options = [...this.options];
  const targetIndex = options.findIndex((option) => {
    const candidate =
      by === "value" ? option.value : (option.text || "").trim();
    return candidate === wanted;
  });
  return JSON.stringify({
    targetIndex,
    selectedIndex: this.selectedIndex,
    multiple: this.multiple,
  });
}
