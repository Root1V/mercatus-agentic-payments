export function truncateAddress(address: string, chars = 6): string {
  if (!address || address.length <= chars * 2 + 2) return address;
  return `${address.slice(0, chars + 2)}…${address.slice(-chars)}`;
}

export function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("es", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function formatUsd(amount: string | number): string {
  const value = typeof amount === "string" ? Number(amount) : amount;
  if (Number.isNaN(value)) return String(amount);
  return `$${value}`;
}
