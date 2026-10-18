import { useEffect, useRef } from "react";
import { Icon, type IconName } from "./Icon";

export type ComposerOption = {
  id: string;
  label: string;
  detail: string;
  icon: IconName;
  select: () => void;
};

export function CommandMenu({
  kind,
  options,
  selected,
  onSelect,
  onHover,
}: {
  kind: "/" | "@";
  options: ComposerOption[];
  selected: number;
  onSelect: (option: ComposerOption) => void;
  onHover: (index: number) => void;
}) {
  const selectedOption = useRef<HTMLButtonElement>(null);
  const selectedId = options[selected]?.id;

  useEffect(() => {
    selectedOption.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selected, selectedId]);

  return (
    <div className="command-menu">
      <div className="command-menu-heading">
        <span>{kind === "/" ? "Shortcuts" : "Tabs & links"}</span>
        <kbd>esc</kbd>
      </div>
      <div
        id="composer-options"
        role="listbox"
        aria-label={kind === "/" ? "Shortcuts" : "Tabs and links"}
      >
        {options.length === 0 ? (
          <p className="menu-empty">
            {kind === "/"
              ? "No matching shortcuts."
              : "No matching tabs. Type @https://… to add a link."}
          </p>
        ) : (
          options.map((option, index) => (
            <button
              type="button"
              ref={index === selected ? selectedOption : undefined}
              role="option"
              id={`composer-option-${index}`}
              aria-selected={selected === index}
              key={option.id}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => onHover(index)}
              onClick={() => onSelect(option)}
            >
              <Icon name={option.icon} />
              <span className="command-copy">
                <strong>{option.label}</strong>
                <span>{option.detail}</span>
              </span>
              {kind === "/" && <code>/{option.id}</code>}
            </button>
          ))
        )}
      </div>
      <p className="menu-hint">
        {kind === "/"
          ? "↑ ↓ to navigate · Enter to select"
          : "Only selected references are shared on send."}
      </p>
    </div>
  );
}
