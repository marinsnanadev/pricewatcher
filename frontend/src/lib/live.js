// Pure helpers that apply a live "product.checked" event to data already on screen.

/** Updates a product (from the list or the detail page) with what the worker just found. */
export function applyChecked(product, event) {
  const next = {
    ...product,
    last_error: event.last_error,
    last_checked_at: event.checked_at,
    next_check_at: event.next_check_at,
    consecutive_failures: event.consecutive_failures,
  };
  if (event.status === "success") {
    next.current_price = event.current_price;
    if (event.changed) {
      next.previousPrice = event.previous_price; // for the % delta
      next.flash = event.current_price < event.previous_price ? "down" : "up";
      next.flashKey = (product.flashKey ?? 0) + 1; // new key = the highlight animation replays
    }
  }
  return next;
}

/** Adds the new price point to a history array (when the worker recorded one). */
export function applyCheckedToHistory(history, event) {
  if (event.status !== "success" || !event.recorded) return history;
  if (history.at(-1)?.collected_at === event.checked_at) return history; // already there
  return [
    ...history,
    {
      id: `live-${event.checked_at}`,
      product_id: event.product_id,
      price: event.current_price,
      collected_at: event.checked_at,
    },
  ];
}
