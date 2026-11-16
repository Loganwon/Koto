import { afterEach, describe, expect, it } from "vitest";
import { mountComponent, upgradeElement } from "./component-bridge";

// Register a minimal custom element for testing
class TestGreeting extends HTMLElement {
  name = "";
}

if (!customElements.get("test-greeting")) {
  customElements.define("test-greeting", TestGreeting);
}

describe("component-bridge", () => {
  let container: HTMLElement;

  afterEach(() => {
    if (container && container.parentNode) container.remove();
  });

  it("mountComponent creates and appends a custom element", () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    const el = mountComponent("test-greeting", container, { name: "Koto" });
    expect(el.tagName.toLowerCase()).toBe("test-greeting");
    expect((el as TestGreeting).name).toBe("Koto");
    expect(container.children[0]).toBe(el);
  });

  it("mountComponent accepts a CSS selector string", () => {
    container = document.createElement("div");
    container.id = "bridge-test";
    document.body.appendChild(container);
    const el = mountComponent("test-greeting", "#bridge-test");
    expect(container.children[0]).toBe(el);
  });

  it("mountComponent throws when container is missing", () => {
    expect(() => mountComponent("test-greeting", "#nonexistent")).toThrow(
      "component-bridge",
    );
  });

  it("upgradeElement replaces an existing element", () => {
    container = document.createElement("div");
    container.innerHTML = '<span id="old-el" data-x="1">Old</span>';
    document.body.appendChild(container);
    const el = upgradeElement("#old-el", "test-greeting", (src) => ({
      name: src.textContent || "",
    }));
    expect(el).not.toBeNull();
    expect((el as TestGreeting).name).toBe("Old");
    expect(container.querySelector("span")).toBeNull();
    expect(container.querySelector("test-greeting")).toBe(el);
  });
});
