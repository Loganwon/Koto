/**
 * Vanilla ↔ Lit interop bridge for progressive migration.
 *
 * Allows existing vanilla TypeScript code to mount Lit components anywhere
 * in the DOM without rewriting the surrounding infrastructure.
 *
 * Usage:
 *   import { mountComponent } from "../shared/component-bridge";
 *   const el = mountComponent("koto-ai-panel", containerEl, { sessionId: "abc" });
 *   // later: el.sessionId = "xyz"; // reactive prop update
 *   // cleanup: el.remove();
 */

export interface ComponentProps {
  [key: string]: unknown;
}

/**
 * Mount a Lit (or any custom) element into a container.
 *
 * Returns the element for property updates and cleanup.
 * The tag must already be registered via customElements.define().
 */
export function mountComponent<T extends HTMLElement>(
  tagName: string,
  container: HTMLElement | string,
  props?: ComponentProps,
): T {
  const el = document.createElement(tagName) as T;
  if (props) {
    const elRec = el as unknown as Record<string, unknown>;
    for (const [key, value] of Object.entries(props)) {
      elRec[key] = value;
    }
  }
  const parent = typeof container === "string"
    ? document.querySelector(container)
    : container;
  if (!parent) {
    throw new Error(`component-bridge: container not found for <${tagName}>`);
  }
  parent.appendChild(el);
  return el;
}

/**
 * Upgrade an existing vanilla DOM subtree by replacing a selector-matched
 * element with a Lit component, preserving its attributes as props.
 */
export function upgradeElement(
  selector: string,
  tagName: string,
  attrToProps?: (el: Element) => ComponentProps,
): HTMLElement | null {
  const source = document.querySelector(selector);
  if (!source) return null;
  const props: ComponentProps = attrToProps ? attrToProps(source) : {};
  const component = document.createElement(tagName);
  const compRec = component as unknown as Record<string, unknown>;
  for (const [key, value] of Object.entries(props)) {
    compRec[key] = value;
  }
  // Copy attributes not already handled
  for (const attr of Array.from(source.attributes)) {
    if (!(attr.name in props)) {
      component.setAttribute(attr.name, attr.value);
    }
  }
  source.replaceWith(component);
  return component;
}
