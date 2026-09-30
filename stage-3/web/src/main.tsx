import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { clearSupersededRejection } from "./booking-attempt";
import "./styles.css";

type RestaurantSummary = { id: string; name: string; timezone: string };
type Opening = { weekday: string; opens: string; closes: string };
type Table = { id: string; label: string; capacity: number };
type Restaurant = RestaurantSummary & {
  can_manage_policies: boolean;
  opening_hours: Opening[];
  tables: Table[];
  combinable: string[][];
  slot_minutes: number;
  reservation_duration_minutes: number;
  cancellation_cutoff_minutes: number;
};
type AvailableOption = { table_ids: string[]; capacity: number };
type AvailabilityRule = { rule: "capacity" | "no_overlap"; holds: boolean };
type TableExplanation = { table_id: string; policy_version: number; available: boolean; rules: AvailabilityRule[] };
type Slot = {
  starts_at_local: string;
  starts_at: string;
  available_table_ids: string[];
  available_options: AvailableOption[];
  explain?: TableExplanation[];
};
type Availability = { restaurant_id: string; date: string; timezone: string; slots: Slot[] };
type AcceptedTerms = {
  policy_version: number;
  slot_minutes: number;
  reservation_duration_minutes: number;
  cancellation_cutoff_minutes: number;
  opening_hours: Opening[];
  capacities: Record<string, number>;
};
type PublishedPolicy = AcceptedTerms & { effective_from: string };
type PoliciesResponse = { policies: PublishedPolicy[] };
type Reservation = {
  reference: string;
  restaurant_id: string;
  table_id?: string;
  table_ids?: string[];
  party_size: number;
  starts_at_local: string;
  starts_at?: string;
  ends_at?: string;
  status: string;
  revision?: number;
  accepted_terms?: AcceptedTerms;
};
type HistoryChange = { field: string; from: unknown; to: unknown };
type HistoryEntry = { seq: number; at: string; event: string; changes: HistoryChange[]; revision: number; accepted_terms: AcceptedTerms };
type ReservationHistory = { reference: string; entries: HistoryEntry[] };
type ReservationDecision = { reference: string; revision: number; accepted_terms: AcceptedTerms };
type SeriesOccurrence = { index: number; reference: string; exception: boolean; reservation: Reservation };
type ReservationSeries = { series_id: string; revision: number; interval_weeks: number; occurrences: SeriesOccurrence[] };
type Selected = { tableIds: string[]; startsAtLocal: string };
type Draft = { restaurantId: string; date: string; party: number; bookingParty?: number; selected: Selected | null };
type Attempt = {
  body: Record<string, unknown>;
  key: string;
  status: "sending" | "uncertain" | "rejected" | "confirmed";
  message?: string;
  receipt?: Reservation;
};
type ApiError = Error & { status: number; code: string };

const AUTH_TOKEN = "tablekeeper.token";
const AUTH_NAME = "tablekeeper.displayName";
const THEME_KEY = "tablekeeper.theme";
const DRAFT_KEY = "tablekeeper.bookingDraft";
const ATTEMPT_KEY = "tablekeeper.bookingAttempt";
const POLICY_ATTEMPT_KEY = "tablekeeper.policyAttempt";
const SERIES_ATTEMPT_KEY = "tablekeeper.seriesAttempt";
const SERIES_ID_KEY = "tablekeeper.lastSeriesId";
const WEEKDAYS = [
  { key: "mon", label: "Monday" }, { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" }, { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" }, { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
];

function token() { return localStorage.getItem(AUTH_TOKEN); }
function revealFeedback(element: HTMLElement | null) {
  if (!element) return;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ behavior: "instant", block: "center" });
}
function localDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function today() { return localDate(new Date()); }
function weekdayFor(value: string) {
  return WEEKDAYS[(new Date(`${value}T12:00:00`).getDay() + 6) % 7].key;
}
function weekdayLabel(value: string) { return WEEKDAYS[(new Date(`${value}T12:00:00`).getDay() + 6) % 7].label; }
function readDraft(): Partial<Draft> {
  try { return JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "{}"); } catch { return {}; }
}
function readAttempt(): Attempt | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(ATTEMPT_KEY) || "null") as Attempt | null;
    return saved?.status === "sending" ? { ...saved, status: "uncertain", message: "We couldn’t confirm the result. Your original request is saved; retry to check the same reservation." } : saved;
  } catch { return null; }
}
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const bearer = token();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch (cause) {
    throw new Error(cause instanceof Error ? cause.message : "Network connection failed.");
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const problem = data?.error;
    if (response.status === 401 && token()) {
      localStorage.removeItem(AUTH_TOKEN);
      localStorage.removeItem(AUTH_NAME);
      window.dispatchEvent(new Event("tablekeeper-auth-expired"));
    }
    const error = new Error(problem?.message || `Request failed (${response.status}).`) as ApiError;
    error.status = response.status;
    error.code = problem?.code || "request_failed";
    throw error;
  }
  return data as T;
}
function storeAuth(data: { token: string; display_name: string }) {
  localStorage.setItem(AUTH_TOKEN, data.token);
  localStorage.setItem(AUTH_NAME, data.display_name);
}
function safeNext() {
  const requested = new URLSearchParams(location.search).get("next") || "/";
  return requested.startsWith("/") && !requested.startsWith("//") ? requested : "/";
}
function tableIds(reservation: Reservation) { return reservation.table_ids || (reservation.table_id ? [reservation.table_id] : []); }
function tableLabel(ids: string[], restaurant?: Restaurant | null) {
  return ids.map((id) => restaurant?.tables.find((table) => table.id === id)?.label || id).join(" + ");
}
function shortDate(value: string) {
  const date = new Date(`${value}T12:00:00`);
  return date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}
function readWriteAttempt(key: string): WriteAttempt | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || "null") as WriteAttempt | null;
    return saved?.status === "sending" ? { ...saved, status: "uncertain", message: "We couldn’t confirm the result. Retry the same request." } : saved;
  } catch { return null; }
}
function readPolicyAttempt(restaurantId: string): PolicyAttempt | null {
  const saved = readWriteAttempt(POLICY_ATTEMPT_KEY);
  return saved ? { ...saved, restaurantId: (saved as PolicyAttempt).restaurantId || restaurantId } : null;
}
function writeMayBeUncertain(error: unknown) {
  return error instanceof Error && (!("status" in error) || (error as ApiError).status >= 500);
}
type WriteAttempt = { key: string; body: Record<string, unknown>; status: "sending" | "uncertain" | "rejected"; message?: string };
type PolicyAttempt = WriteAttempt & { restaurantId: string };

function TermsSummary({ terms, restaurant }: { terms: AcceptedTerms; restaurant?: Restaurant | null }) {
  const capacities = restaurant?.tables.map((table) => `${table.label}: ${terms.capacities[table.id] ?? "—"}`).join(" · ")
    || Object.entries(terms.capacities).map(([id, capacity]) => `${id}: ${capacity}`).join(" · ");
  const hours = WEEKDAYS.map(({ key, label }) => {
    const value = terms.opening_hours.find((item) => item.weekday === key);
    return `${label}: ${value ? `${value.opens}–${value.closes}` : "Closed"}`;
  }).join(" · ");
  return <section className="terms-summary" data-testid="accepted-terms">
    <p><strong>Accepted terms</strong> · Policy {terms.policy_version} · {terms.slot_minutes}-minute slots · {terms.reservation_duration_minutes}-minute reservation · {terms.cancellation_cutoff_minutes}-minute cancellation cutoff</p>
    <details><summary>Full accepted terms</summary><p><strong>Opening hours:</strong> {hours}</p><p><strong>Table capacities:</strong> {capacities}</p></details>
  </section>;
}

function displayHistoryValue(value: unknown) {
  if (value === null) return "—";
  if (Array.isArray(value)) return value.join(" + ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function optionCapacity(ids: string[], slot: Slot, restaurant: Restaurant, policies: PublishedPolicy[]) {
  const available = slot.available_options?.find((item) => item.table_ids.join("+") === ids.join("+"));
  if (available) return available.capacity;
  const version = slot.explain?.[0]?.policy_version ?? 0;
  const policy = policies.find((item) => item.policy_version === version);
  return ids.reduce((sum, id) => sum + (policy?.capacities[id] ?? restaurant.tables.find((table) => table.id === id)?.capacity ?? 0), 0);
}

function unavailabilityReason(ids: string[], slot: Slot, partySize: number, restaurant: Restaurant, policies: PublishedPolicy[]) {
  const capacity = optionCapacity(ids, slot, restaurant, policies);
  const hasOverlap = slot.explain?.some((item) => ids.includes(item.table_id) && !item.rules.find((rule) => rule.rule === "no_overlap")?.holds) || false;
  const reasons = [
    ...(partySize > capacity ? [`Party of ${partySize} exceeds capacity ${capacity}`] : []),
    ...(hasOverlap ? ["A confirmed reservation overlaps this time"] : []),
  ];
  return reasons.length ? reasons : ["This option is not currently available"];
}

function App() {
  const [user, setUser] = useState(() => localStorage.getItem(AUTH_NAME));
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  useEffect(() => {
    const update = () => setUser(localStorage.getItem(AUTH_NAME));
    window.addEventListener("tablekeeper-auth-expired", update);
    return () => window.removeEventListener("tablekeeper-auth-expired", update);
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem(THEME_KEY, theme); }, [theme]);
  const logout = () => {
    localStorage.removeItem(AUTH_TOKEN);
    localStorage.removeItem(AUTH_NAME);
    setUser(null);
  };
  const path = window.location.pathname;
  return <>
    <header className="site-header">
      <a className="brand" href="/" aria-label="Tablekeeper home"><span className="brand-mark">t</span><span>tablekeeper</span></a>
      <nav aria-label="Main navigation">
        <a href="/">Find a table</a>
        <a href="/lookup">Your booking</a>
        {user ? <span className="account-nav"><span data-testid="current-user">{user}</span><button data-testid="logout-button" className="text-button" onClick={logout}>Sign out</button></span> : <a href="/login">Sign in</a>}
        <button className="theme-toggle" data-testid="theme-toggle" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}><span aria-hidden="true">{theme === "dark" ? "☼" : "☾"}</span><span className="theme-label">{theme === "dark" ? "Light" : "Dark"}</span></button>
      </nav>
    </header>
    {path === "/login" ? <AuthPage mode="login" /> : path === "/signup" ? <AuthPage mode="signup" /> : path === "/lookup" ? <LookupPage signedIn={Boolean(user)} /> : <HomePage signedIn={Boolean(user)} />}
    <footer className="site-footer"><span>Good food starts with a good table.</span><span>Thoughtful reservations, made simple.</span></footer>
  </>;
}

function HomePage({ signedIn }: { signedIn: boolean }) {
  const saved = useMemo(readDraft, []);
  const [restaurants, setRestaurants] = useState<RestaurantSummary[]>([]);
  const [restaurantId, setRestaurantId] = useState(saved.restaurantId || "");
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [policies, setPolicies] = useState<PublishedPolicy[]>([]);
  const [policyLoadError, setPolicyLoadError] = useState("");
  const [policyLoading, setPolicyLoading] = useState(false);
  const [date, setDate] = useState(saved.date || today());
  const [party, setParty] = useState(saved.party || 2);
  const [bookingParty, setBookingParty] = useState(saved.bookingParty || saved.party || 2);
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [searchError, setSearchError] = useState("");
  const [loadingRestaurants, setLoadingRestaurants] = useState(true);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Selected | null>(saved.selected || null);
  const [attempt, setAttempt] = useState<Attempt | null>(readAttempt());
  const [authError, setAuthError] = useState(Boolean(saved.selected && !token()));
  const [restoreError, setRestoreError] = useState("");
  const searchSequence = useRef(0);
  const reviewRef = useRef<HTMLElement>(null);
  const bookingErrorRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    let current = true;
    api<{ restaurants: RestaurantSummary[] }>("/restaurants").then((data) => {
      if (!current) return;
      setRestaurants(data.restaurants);
      setRestaurantId((existing) => data.restaurants.some((item) => item.id === existing) ? existing : data.restaurants[0]?.id || "");
    }).catch((error) => { if (current) setSearchError(error.message); }).finally(() => { if (current) setLoadingRestaurants(false); });
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!restaurantId) return;
    let current = true;
    setRestaurant(null);
    api<Restaurant>(`/restaurants/${encodeURIComponent(restaurantId)}`).then((data) => {
      if (current) setRestaurant(data);
    }).catch((error) => { if (current) setSearchError(error.message); });
    return () => { current = false; };
  }, [restaurantId]);

  useEffect(() => {
    if (!restaurantId) return;
    let current = true;
    setPolicies([]);
    setPolicyLoadError("");
    setPolicyLoading(true);
    api<PoliciesResponse>(`/restaurants/${encodeURIComponent(restaurantId)}/policies`).then((result) => {
      if (current) setPolicies(result.policies);
    }).catch((error) => {
      if (current) setPolicyLoadError(error instanceof Error ? error.message : "Published policies could not be loaded.");
    }).finally(() => { if (current) setPolicyLoading(false); });
    return () => { current = false; };
  }, [restaurantId]);

  useEffect(() => {
    const draft = { restaurantId, date, party, bookingParty, selected };
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  }, [restaurantId, date, party, bookingParty, selected]);
  useEffect(() => {
    if (attempt) sessionStorage.setItem(ATTEMPT_KEY, JSON.stringify(attempt));
    else sessionStorage.removeItem(ATTEMPT_KEY);
  }, [attempt]);
  useEffect(() => {
    if (attempt?.status === "rejected" && !searching) revealFeedback(bookingErrorRef.current);
  }, [searching, attempt?.status, attempt?.key, attempt?.message]);

  const options = useMemo(() => {
    if (!restaurant) return [] as { ids: string[]; label: string; capacity: number }[];
    const singles = restaurant.tables.map((table) => ({ ids: [table.id], label: table.label, capacity: table.capacity }));
    const pairs = restaurant.combinable.map((ids) => ({
      ids,
      label: `${tableLabel([ids[0]], restaurant)} + ${tableLabel([ids[1]], restaurant)}`,
      capacity: ids.reduce((sum, id) => sum + (restaurant.tables.find((table) => table.id === id)?.capacity || 0), 0),
    }));
    return [...singles, ...pairs];
  }, [restaurant]);

  const bookingBodyFor = (next: Selected | null, partySize = bookingParty) => {
    if (!next || !restaurant) return null;
    return {
      restaurant_id: restaurant.id,
      ...(next.tableIds.length === 1 ? { table_id: next.tableIds[0] } : { table_ids: next.tableIds }),
      starts_at_local: next.startsAtLocal,
      party_size: Number(partySize),
    };
  };
  const clearStaleRejection = (next: Selected | null, partySize = bookingParty) => {
    const nextBody = bookingBodyFor(next, partySize);
    setAttempt((previous) => clearSupersededRejection(previous, nextBody));
  };

  const runSearch = async (event?: FormEvent, clearSelection = true, force = false) => {
    event?.preventDefault();
    if (!restaurant || !date || party < 1 || (!force && (attempt?.status === "uncertain" || attempt?.status === "sending"))) return;
    const sequence = ++searchSequence.current;
    setSearching(true);
    setSearchError("");
    setAvailability(null);
    if (clearSelection) { setSelected(null); setAuthError(false); clearStaleRejection(null); }
    try {
      const query = new URLSearchParams({ restaurant_id: restaurant.id, date, party_size: String(party), explain: "true" });
      const result = await api<Availability>(`/availability?${query}`);
      if (sequence === searchSequence.current) setAvailability(result);
    } catch (error) {
      if (sequence === searchSequence.current) setSearchError(error instanceof Error ? error.message : "Availability could not be loaded.");
    } finally {
      if (sequence === searchSequence.current) setSearching(false);
    }
  };

  const setSearchField = () => { searchSequence.current += 1; setAvailability(null); setSearchError(""); clearStaleRejection(null); };
  const refreshAvailability = () => runSearch(undefined, false, true);
  const choose = (value: Selected) => {
    if (attempt?.status === "uncertain" || attempt?.status === "sending") return;
    clearStaleRejection(value, party);
    setSelected(value);
    setBookingParty(party);
    setAuthError(!signedIn);
    setRestoreError("");
    const shouldBringReviewIntoView = window.matchMedia("(max-width: 760px)").matches || (reviewRef.current?.getBoundingClientRect().top || 0) > window.innerHeight * 0.45;
    requestAnimationFrame(() => {
      if (shouldBringReviewIntoView) reviewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      if (!signedIn) document.getElementById("auth-error")?.focus({ preventScroll: true });
    });
  };

  const selectedOption = selected && options.find((option) => option.ids.join("+") === selected.tableIds.join("+"));
  const currentBody = bookingBodyFor(selected);
  const effectivePolicy = policies.filter((item) => item.effective_from <= date)
    .sort((a, b) => a.effective_from.localeCompare(b.effective_from) || a.policy_version - b.policy_version).at(-1);
  const displayedOptions = options.map((option) => ({
    ...option,
    capacity: option.ids.reduce((sum, id) => sum + (effectivePolicy?.capacities[id] ?? restaurant?.tables.find((table) => table.id === id)?.capacity ?? 0), 0),
  }));

  const book = async () => {
    if (!selected || !restaurant || !currentBody) return;
    if (!token()) { setAuthError(true); return; }
    if (attempt?.status === "sending") return;
    if (attempt?.status === "uncertain") {
      await sendAttempt(attempt);
      return;
    }
    const bodyText = JSON.stringify(currentBody);
    const reusable = attempt && JSON.stringify(attempt.body) === bodyText;
    const nextAttempt: Attempt = {
      body: currentBody,
      key: reusable ? attempt.key : crypto.randomUUID(),
      status: "sending",
      receipt: reusable ? attempt.receipt : undefined,
    };
    setAuthError(false);
    setRestoreError("");
    setAttempt(nextAttempt);
    await sendAttempt(nextAttempt);
  };

  const sendAttempt = async (previous: Attempt) => {
    const sending = { ...previous, status: "sending" as const, message: undefined };
    sessionStorage.setItem(ATTEMPT_KEY, JSON.stringify(sending));
    setAttempt(sending);
    try {
      const receipt = await api<Reservation>("/reservations", {
        method: "POST",
        headers: { "Idempotency-Key": previous.key },
        body: JSON.stringify(previous.body),
      });
      setAttempt({ ...previous, status: "confirmed", receipt, message: undefined });
    } catch (error) {
      if (error instanceof Error && (!('status' in error) || (error as ApiError).status >= 500)) {
        setAttempt({ ...previous, status: "uncertain", message: "We couldn’t confirm the result. Your original request is saved; retry to check the same reservation." });
        return;
      }
      const failure = error as ApiError;
      setAttempt({ ...previous, status: "rejected", message: failure.message || "The reservation was declined. Your details are still here." });
      if (failure.status === 409) void refreshAvailability();
    }
  };

  const useRestoredBooking = () => {
    if (!restaurant || !selected) return;
    setRestoreError("");
    const savedAttempt = attempt;
    if (savedAttempt?.status === "uncertain") void sendAttempt(savedAttempt);
    else void book();
  };

  const locked = attempt?.status === "uncertain" || attempt?.status === "sending";
  const closed = restaurant && date && !restaurant.opening_hours.some((hours) => hours.weekday === weekdayFor(date));
  return <main className="page-shell home-page">
    <section className="hero" aria-labelledby="home-title">
      <div className="hero-copy"><p className="eyebrow">A seat at the table</p><h1 id="home-title">Make room for a<br /><em>good evening.</em></h1><p>Find the right table for the people and plans that matter.</p><div className="hero-note"><span className="olive-dot" /> Thoughtful tables. Clear plans. No guesswork.</div></div>
      <div className="hero-art"><img src="/assets/restaurant-illustration.png" alt="A welcoming restaurant table set for dinner" /><img className="hero-plant" src="/assets/plant.svg" alt="" /></div>
    </section>
    <section className="search-card" aria-labelledby="search-title">
      <div className="section-heading"><div><p className="eyebrow">Start with the details</p><h2 id="search-title">Find your table</h2></div><img src="/assets/window.svg" alt="" /></div>
      <form className="search-form" onSubmit={runSearch}>
        <label>Restaurant<select data-testid="restaurant-select" value={restaurantId} disabled={loadingRestaurants || locked} onChange={(event) => { setRestaurantId(event.target.value); setSearchField(); setSelected(null); }} required>{restaurants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Date<input data-testid="date-input" type="date" value={date} disabled={locked} onChange={(event) => { setDate(event.target.value); setSearchField(); setSelected(null); }} required /></label>
        <label>Party size<input data-testid="party-size-input" type="number" min="1" step="1" value={party} disabled={locked} onChange={(event) => { setParty(Number(event.target.value)); setSearchField(); setSelected(null); }} required /></label>
        <button className="button button-primary search-button" data-testid="search-button" type="submit" disabled={loadingRestaurants || !restaurant || searching || locked}>{searching ? "Finding tables…" : "Find a table"}<span aria-hidden="true">↗</span></button>
      </form>
      {loadingRestaurants && <p className="inline-status" role="status">Loading restaurant choices…</p>}
      {!loadingRestaurants && !restaurants.length && <p className="empty-state">No restaurants are available yet.</p>}
      {restaurantId && !restaurant && !searchError && <p className="inline-status" role="status">Loading restaurant details…</p>}
      {searchError && <p className="message message-error" role="alert" data-testid="availability-error">{searchError}</p>}
      {restaurant && <div className="hours-strip" aria-label="Restaurant opening hours"><span className="hours-title">Open through the week</span><div className="hours-days">{WEEKDAYS.map(({ key, label }) => { const hours = restaurant.opening_hours.find((item) => item.weekday === key); return <span key={key}><b>{label.slice(0, 3)}</b><small>{hours ? `${hours.opens}–${hours.closes}` : "Closed"}</small></span>; })}</div></div>}
    </section>
    {availability && <section className="results-section" aria-labelledby="results-title">
      <div className="results-heading"><div><p className="eyebrow">A few good options</p><h2 id="results-title">{shortDate(availability.date)}</h2></div><span className="timezone-label">Local time · {availability.timezone}</span></div>
      {closed ? <p className="empty-state" data-testid="no-slots">This restaurant is closed on {weekdayLabel(date)}. Choose another date to see available tables.</p> : availability.slots.length === 0 ? <p className="empty-state" data-testid="no-slots">There are no reservation times on this date.</p> : (
        <div className="results-viewport" data-testid="availability-grid" aria-label="Table availability by time">
          {displayedOptions.map((option) => <section className="table-group" key={option.ids.join("+")} aria-label={option.label}>
            <div className="table-group-label"><img src="/assets/picnic-table.svg" alt="" /><div><strong>{option.label}</strong><small>Up to {option.capacity} guests</small></div></div>
            <div className="time-cells">{availability.slots.map((slot) => {
              const time = slot.starts_at_local.slice(11, 16);
              const isAvailable = slot.available_options?.some((available) => available.table_ids.join("+") === option.ids.join("+")) || (option.ids.length === 1 && slot.available_table_ids.includes(option.ids[0]));
              const isSelected = selected?.tableIds.join("+") === option.ids.join("+") && selected.startsAtLocal === slot.starts_at_local;
              const reasons = isAvailable || !restaurant ? [] : unavailabilityReason(option.ids, slot, party, restaurant, policies);
              const reasonLabel = reasons.length > 1 ? "Capacity + busy" : reasons[0]?.startsWith("Party") ? "Capacity" : reasons.length ? "Occupied" : "";
              const reasonText = reasons.join("; ");
              return <button key={slot.starts_at_local} type="button" className={`time-cell${isSelected ? " is-selected" : ""}`} data-testid={`slot-${option.ids.join("+")}-${time}`} data-available={String(isAvailable)} aria-label={`${option.label}, ${time}, ${isAvailable ? "available" : `unavailable: ${reasonText}`}`} aria-pressed={isSelected} title={isAvailable ? `Select ${time}` : reasonText} disabled={!isAvailable || locked} onClick={() => choose({ tableIds: option.ids, startsAtLocal: slot.starts_at_local })}>{time}{reasonLabel && <small className="cell-reason" aria-hidden="true">{reasonLabel}</small>}</button>;
            })}</div>
          </section>)}
        </div>
      )}
      <p className="legend"><span className="legend-chip" /> Available <span className="legend-chip legend-unavailable" /> Unavailable</p>
    </section>}
    <section className={`reservation-panel${selected ? " has-selection" : ""}`} aria-labelledby="review-title" ref={reviewRef} data-testid="reservation-panel">
      <div className="review-title-row"><div><p className="eyebrow">Your evening, taking shape</p><h2 id="review-title">Reservation review</h2></div><span className="review-step">01 <i>/ 01</i></span></div>
      {selected ? <>
        <form data-testid="booking-form" onSubmit={(event) => { event.preventDefault(); attempt?.status === "uncertain" ? useRestoredBooking() : book(); }}>
          <p className="selected-summary" data-testid="booking-summary"><strong>{restaurants.find((item) => item.id === restaurantId)?.name || "Your restaurant"}</strong><span>{shortDate(selected.startsAtLocal.slice(0, 10))} · {selected.startsAtLocal.slice(11, 16)}</span><span>{selectedOption?.label || tableLabel(selected.tableIds, restaurant)}</span></p>
          <label className="booking-party-field">Party size<input data-testid="booking-party-size" type="number" min="1" step="1" value={bookingParty} disabled={locked} onChange={(event) => { const value = Number(event.target.value); clearStaleRejection(selected, value); setBookingParty(value); }} required /></label>
          {!signedIn && <><a className="button button-outline sign-in-action" href="/login?next=%2F">Sign in</a>{authError && <p id="auth-error" className="message message-error auth-panel-error" role="alert" tabIndex={-1} data-testid="auth-error">Please sign in before completing your reservation. Your table selection is saved.</p>}</>}
          {restoreError && <p className="message message-error" role="alert">{restoreError}</p>}
          {attempt?.status === "uncertain" && <p className="message message-warning" role="status" data-testid="booking-uncertain">{attempt.message}</p>}
          {attempt?.status === "rejected" && <p ref={bookingErrorRef} id="booking-error" className="message message-error booking-error" role="alert" tabIndex={-1} data-testid="booking-error">{attempt.message}</p>}
          {attempt?.status === "confirmed" && attempt.receipt && currentBody && JSON.stringify(attempt.body) === JSON.stringify(currentBody) && <div className="receipt" role="status" data-testid="confirmation"><span className="receipt-kicker">Reservation confirmed</span><strong data-testid="confirmation-reference">{attempt.receipt.reference}</strong><span data-testid="confirmation-details">{restaurants.find((item) => item.id === attempt.receipt?.restaurant_id)?.name || attempt.receipt.restaurant_id} · {tableLabel(tableIds(attempt.receipt), restaurant)} · {attempt.receipt.starts_at_local.replace("T", " ")}</span><span data-testid="confirmation-tables">{tableLabel(tableIds(attempt.receipt), restaurant)}</span>{attempt.receipt.accepted_terms && <TermsSummary terms={attempt.receipt.accepted_terms} restaurant={restaurant} />}</div>}
          <button className="button button-primary review-submit" data-testid="booking-submit" type="submit" disabled={!selected || attempt?.status === "sending"} aria-describedby={authError ? "auth-error" : attempt?.status === "rejected" ? "booking-error" : undefined}>{attempt?.status === "sending" ? "Saving your table…" : attempt?.status === "uncertain" ? "Retry reservation" : "Reserve this table"}<span aria-hidden="true">↗</span></button>
          <p className="review-caption">Nothing is held until the reservation is confirmed.</p>
        </form>
      </> : <div className="review-empty"><span className="review-icon"><img src="/assets/tools-kitchen-2.svg" alt="" /></span><p>Select an available time to review your reservation here.</p><small>Your date, party size and chosen table stay together.</small></div>}
    </section>
    {restaurant && <PolicyEditor restaurant={restaurant} policies={policies} loading={policyLoading} loadError={policyLoadError} signedIn={signedIn} onPublished={(restaurantId, policy) => { if (restaurantId === restaurant.id) setPolicies((previous) => [...previous.filter((item) => item.policy_version !== policy.policy_version), policy].sort((a, b) => a.policy_version - b.policy_version)); }} />}
  </main>;
}

function PolicyEditor({ restaurant, policies, loading, loadError, signedIn, onPublished }: {
  restaurant: Restaurant;
  policies: PublishedPolicy[];
  loading: boolean;
  loadError: string;
  signedIn: boolean;
  onPublished: (restaurantId: string, policy: PublishedPolicy) => void;
}) {
  const [effectiveFrom, setEffectiveFrom] = useState(today());
  const [slotMinutes, setSlotMinutes] = useState(restaurant.slot_minutes);
  const [duration, setDuration] = useState(restaurant.reservation_duration_minutes);
  const [cutoff, setCutoff] = useState(restaurant.cancellation_cutoff_minutes);
  const [hours, setHours] = useState(restaurant.opening_hours);
  const [capacities, setCapacities] = useState(() => Object.fromEntries(restaurant.tables.map((table) => [table.id, table.capacity])));
  const [attempt, setAttempt] = useState<PolicyAttempt | null>(() => readPolicyAttempt(restaurant.id));
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [successRestaurantId, setSuccessRestaurantId] = useState(restaurant.id);
  const restaurantIdRef = useRef(restaurant.id);
  restaurantIdRef.current = restaurant.id;

  useEffect(() => {
    const latest = [...policies].sort((a, b) => a.policy_version - b.policy_version).at(-1);
    setSlotMinutes(latest?.slot_minutes ?? restaurant.slot_minutes);
    setDuration(latest?.reservation_duration_minutes ?? restaurant.reservation_duration_minutes);
    setCutoff(latest?.cancellation_cutoff_minutes ?? restaurant.cancellation_cutoff_minutes);
    setHours(latest?.opening_hours ?? restaurant.opening_hours);
    setCapacities(Object.fromEntries(restaurant.tables.map((table) => [table.id, latest?.capacities[table.id] ?? table.capacity])));
  }, [restaurant, policies]);

  const send = async (previous: PolicyAttempt) => {
    if (previous.restaurantId !== restaurant.id) return;
    const sending = { ...previous, status: "sending" as const, message: undefined };
    setAttempt(sending);
    sessionStorage.setItem(POLICY_ATTEMPT_KEY, JSON.stringify(sending));
    setError("");
    setSuccess("");
    setSuccessRestaurantId(previous.restaurantId);
    try {
      const published = await api<PublishedPolicy>(`/restaurants/${encodeURIComponent(previous.restaurantId)}/policies`, {
        method: "POST", headers: { "Idempotency-Key": previous.key }, body: JSON.stringify(previous.body),
      });
      sessionStorage.removeItem(POLICY_ATTEMPT_KEY);
      setAttempt(null);
      setSuccess(`Published policy ${published.policy_version}, effective ${published.effective_from}.`);
      if (restaurantIdRef.current === previous.restaurantId) onPublished(previous.restaurantId, published);
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : "Policy publication could not be confirmed.";
      if (writeMayBeUncertain(failure)) {
        const uncertain = { ...previous, status: "uncertain" as const, message: `Publication result is uncertain. ${message} Retry to check the same policy.` };
        sessionStorage.setItem(POLICY_ATTEMPT_KEY, JSON.stringify(uncertain));
        setAttempt(uncertain);
        setError(uncertain.message || message);
      } else {
        sessionStorage.removeItem(POLICY_ATTEMPT_KEY);
        setAttempt({ ...previous, status: "rejected", message });
        setError(message);
      }
    }
  };

  const publish = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!signedIn || attempt?.status === "sending") return;
    if (attempt?.status === "uncertain") { if (attempt.restaurantId === restaurant.id) await send(attempt); return; }
    const body = {
      effective_from: effectiveFrom,
      slot_minutes: Number(slotMinutes),
      reservation_duration_minutes: Number(duration),
      cancellation_cutoff_minutes: Number(cutoff),
      opening_hours: WEEKDAYS.flatMap(({ key }) => hours.filter((item) => item.weekday === key)),
      capacities: Object.fromEntries(restaurant.tables.map((table) => [table.id, Number(capacities[table.id])])),
    };
    await send({ restaurantId: restaurant.id, body, key: crypto.randomUUID(), status: "sending" });
  };

  const attemptForRestaurant = attempt?.restaurantId === restaurant.id;
  const locked = attempt?.status === "sending" || attempt?.status === "uncertain";
  return <details className="policy-card" data-testid="policy-management">
    <summary>Restaurant policies</summary>
    <div className="policy-content">
      <h2>Published booking policies</h2>
      {loading && <p className="inline-status" role="status">Loading published policies…</p>}
      {loadError && <p className="message message-error" role="alert" data-testid="policy-list-error">{loadError}</p>}
      {!loading && !loadError && policies.length === 0 && <p className="inline-status">No dated policies have been published.</p>}
      {policies.length > 0 && <ol className="policy-list" data-testid="policy-list">
        {[...policies].sort((a, b) => a.policy_version - b.policy_version).map((policy) => <li key={policy.policy_version} data-testid={`policy-version-${policy.policy_version}`}>
          <strong>Policy {policy.policy_version}</strong><span>Effective {policy.effective_from}</span>
          <small>{policy.slot_minutes}-minute slots · {policy.reservation_duration_minutes}-minute reservations · {policy.cancellation_cutoff_minutes}-minute cancellation cutoff</small>
        </li>)}
      </ol>}
      {!signedIn ? <p className="inline-status">Sign in with a restaurant manager account to publish a policy.</p> : !restaurant.can_manage_policies ? <p className="inline-status" data-testid="policy-manager-access">This account is not a manager of this restaurant and cannot publish policies.</p> : <form className="policy-form" data-testid="policy-publish-form" onSubmit={publish}>
        <h3>Publish a complete policy</h3>
        {attempt?.status === "uncertain" && !attemptForRestaurant && <p className="message message-warning" role="status">A publication is still uncertain for restaurant {attempt.restaurantId}. Select that restaurant to retry the original request.</p>}
        <label>Effective from<input data-testid="policy-effective-from" type="date" value={effectiveFrom} disabled={locked} onChange={(event) => setEffectiveFrom(event.target.value)} required /></label>
        <div className="policy-numbers">
          <label>Slot minutes<input data-testid="policy-slot-minutes" type="number" min="1" max="1440" step="1" value={slotMinutes} disabled={locked} onChange={(event) => setSlotMinutes(Number(event.target.value))} required /></label>
          <label>Reservation minutes<input data-testid="policy-duration" type="number" min="1" max="1440" step="1" value={duration} disabled={locked} onChange={(event) => setDuration(Number(event.target.value))} required /></label>
          <label>Cancellation cutoff minutes<input data-testid="policy-cutoff" type="number" min="0" max="10080" step="1" value={cutoff} disabled={locked} onChange={(event) => setCutoff(Number(event.target.value))} required /></label>
        </div>
        <fieldset className="policy-hours"><legend>Opening hours</legend>
          {WEEKDAYS.map(({ key, label }) => {
            const existing = hours.find((item) => item.weekday === key);
            return <div className="policy-day" key={key}>
              <label className="policy-day-toggle"><input type="checkbox" data-testid={`policy-open-${key}`} checked={Boolean(existing)} disabled={locked} onChange={(event) => setHours((previous) => event.target.checked ? [...previous, { weekday: key, opens: "18:00", closes: "23:00" }].sort((a, b) => WEEKDAYS.findIndex((day) => day.key === a.weekday) - WEEKDAYS.findIndex((day) => day.key === b.weekday)) : previous.filter((item) => item.weekday !== key))} />{label}</label>
              {existing && <><label>{label} opens<input data-testid={`policy-opens-${key}`} type="time" value={existing.opens} disabled={locked} onChange={(event) => setHours((previous) => previous.map((item) => item.weekday === key ? { ...item, opens: event.target.value } : item))} required /></label><label>{label} closes<input data-testid={`policy-closes-${key}`} type="time" value={existing.closes} disabled={locked} onChange={(event) => setHours((previous) => previous.map((item) => item.weekday === key ? { ...item, closes: event.target.value } : item))} required /></label></>}
            </div>;
          })}
        </fieldset>
        <fieldset className="policy-capacities"><legend>Table capacities</legend>
          {restaurant.tables.map((table) => <label key={table.id}>{table.label}<input data-testid={`policy-capacity-${table.id}`} type="number" min="1" max="100" step="1" value={capacities[table.id] ?? table.capacity} disabled={locked} onChange={(event) => setCapacities((previous) => ({ ...previous, [table.id]: Number(event.target.value) }))} required /></label>)}
        </fieldset>
        {attemptForRestaurant && attempt?.status === "uncertain" && <p className="message message-warning" role="status" data-testid="policy-uncertain">{attempt.message}</p>}
        {attemptForRestaurant && error && <p id="policy-error" className="message message-error" role="alert" data-testid="policy-error">{error}</p>}
        {successRestaurantId === restaurant.id && success && <p className="message message-success" role="status" data-testid="policy-success">{success}</p>}
        <button className="button button-primary" data-testid="policy-publish" type="submit" disabled={(attemptForRestaurant && attempt?.status === "sending") || (attempt?.status === "uncertain" && !attemptForRestaurant)} aria-describedby={attemptForRestaurant && error ? "policy-error" : undefined}>{attempt?.status === "sending" ? "Publishing…" : attempt?.status === "uncertain" ? "Retry policy publication" : "Publish policy"}</button>
        <p className="inline-status">The server checks manager membership for this account.</p>
      </form>}
    </div>
  </details>;
}

function ReservationHistoryDisclosure({ reference, restaurant }: { reference: string; restaurant: Restaurant | null }) {
  const [history, setHistory] = useState<ReservationHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    if (loading || history) return;
    setLoading(true);
    setError("");
    try {
      setHistory(await api<ReservationHistory>(`/reservations/${encodeURIComponent(reference)}/history`));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Reservation history could not be loaded.");
    } finally { setLoading(false); }
  };
  return <details className="history-disclosure" data-testid="reservation-history" onToggle={(event) => { if (event.currentTarget.open) void load(); }}>
    <summary>Reservation history</summary>
    {loading && <p className="inline-status" role="status">Loading owner history…</p>}
    {error && <div><p className="message message-error" role="alert" data-testid="history-error">{error}</p><button className="button button-outline" type="button" onClick={() => { setHistory(null); void load(); }}>Retry history</button></div>}
    {history && <ol className="history-list">
      {history.entries.map((entry) => <li key={entry.seq} data-testid={`history-entry-${entry.seq}`}>
        <div className="history-event"><strong>{entry.event} · revision {entry.revision}</strong><time dateTime={entry.at}>{new Date(entry.at).toLocaleString()}</time></div>
        {entry.changes.length > 0 ? <ul>{entry.changes.map((change, index) => <li key={`${change.field}-${index}`}>{change.field}: {displayHistoryValue(change.from)} → {displayHistoryValue(change.to)}</li>)}</ul> : <p>No reservation fields changed.</p>}
        <details><summary>Terms at this event</summary><TermsSummary terms={entry.accepted_terms} restaurant={restaurant} /></details>
      </li>)}
    </ol>}
  </details>;
}

function SeriesPanel({ reservation, restaurant }: { reservation: Reservation; restaurant: Restaurant | null }) {
  const querySeriesId = new URLSearchParams(location.search).get("series_id");
  const [seriesId, setSeriesId] = useState(() => querySeriesId || sessionStorage.getItem(SERIES_ID_KEY) || "");
  const [series, setSeries] = useState<ReservationSeries | null>(null);
  const [count, setCount] = useState(4);
  const [intervalWeeks, setIntervalWeeks] = useState(1);
  const [attempt, setAttempt] = useState<WriteAttempt | null>(() => readWriteAttempt(SERIES_ATTEMPT_KEY));
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState("");
  const [cancelError, setCancelError] = useState("");
  const [cancelErrorReference, setCancelErrorReference] = useState("");

  const refresh = async (id: string) => {
    setLoading(true);
    setLoadError("");
    try {
      const current = await api<ReservationSeries>(`/series/${encodeURIComponent(id)}`);
      if (!current.occurrences.some((item) => item.reference === reservation.reference)) {
        setSeries(null);
        setSeriesId("");
        sessionStorage.removeItem(SERIES_ID_KEY);
        return;
      }
      setSeries(current);
      setSeriesId(id);
      sessionStorage.setItem(SERIES_ID_KEY, id);
    } catch (failure) {
      setLoadError(failure instanceof Error ? failure.message : "Series details could not be loaded.");
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (seriesId) void refresh(seriesId);
  }, [seriesId, reservation.reference]);

  const send = async (previous: WriteAttempt) => {
    const sending = { ...previous, status: "sending" as const, message: undefined };
    setAttempt(sending);
    sessionStorage.setItem(SERIES_ATTEMPT_KEY, JSON.stringify(sending));
    setError("");
    setSuccess("");
    try {
      const created = await api<ReservationSeries>("/series", {
        method: "POST", headers: { "Idempotency-Key": previous.key }, body: JSON.stringify(previous.body),
      });
      sessionStorage.removeItem(SERIES_ATTEMPT_KEY);
      setAttempt(null);
      sessionStorage.setItem(SERIES_ID_KEY, created.series_id);
      setSeriesId(created.series_id);
      setSeries(created);
      setSuccess(`Recurring agreement created with ${created.occurrences.length} occurrences.`);
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : "Recurring agreement could not be confirmed.";
      if (writeMayBeUncertain(failure)) {
        const uncertain = { ...previous, status: "uncertain" as const, message: `The result is uncertain. ${message} Retry the same request.` };
        sessionStorage.setItem(SERIES_ATTEMPT_KEY, JSON.stringify(uncertain));
        setAttempt(uncertain);
        setError(uncertain.message || message);
      } else {
        sessionStorage.removeItem(SERIES_ATTEMPT_KEY);
        setAttempt({ ...previous, status: "rejected", message });
        setError(message);
      }
    }
  };

  const adopt = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (reservation.status !== "confirmed" || attempt?.status === "sending") return;
    if (attempt?.status === "uncertain") { await send(attempt); return; }
    await send({ body: { anchor_reference: reservation.reference, count: Number(count), interval_weeks: Number(intervalWeeks) }, key: crypto.randomUUID(), status: "sending" });
  };

  const cancelOccurrence = async (reference: string) => {
    if (cancelling) return;
    setCancelling(reference);
    setCancelError("");
    setCancelErrorReference("");
    try {
      await api<Reservation>(`/reservations/${encodeURIComponent(reference)}/cancel`, { method: "POST" });
    } catch (failure) {
      setCancelError(failure instanceof Error ? `${failure.message} Check the occurrence status.` : "Cancellation could not be confirmed. Check the occurrence status.");
      setCancelErrorReference(reference);
    } finally {
      if (seriesId) await refresh(seriesId);
      setCancelling("");
    }
  };

  const pendingAnchor = typeof attempt?.body.anchor_reference === "string" ? attempt.body.anchor_reference : "";
  const hasSeries = Boolean(series && series.occurrences.some((item) => item.reference === reservation.reference));
  return <section className="series-panel" data-testid="series-panel" aria-labelledby="series-title">
    <div className="section-heading"><div><p className="eyebrow">Make it a regular thing</p><h2 id="series-title">Recurring visits</h2></div></div>
    {loading && <p className="inline-status" role="status">Loading current occurrences…</p>}
    {loadError && <p className="message message-error" role="alert" data-testid="series-error">{loadError}</p>}
    {!hasSeries && reservation.status === "confirmed" && <form className="series-form" data-testid="series-create-form" onSubmit={adopt}>
      <p>Adopt this confirmed reservation as occurrence zero. Each future date is checked against its actual opening hours, policy and availability.</p>
      <div className="series-fields">
        <label>Occurrences, including this booking<select data-testid="series-count" value={count} disabled={attempt?.status === "sending" || attempt?.status === "uncertain"} onChange={(event) => setCount(Number(event.target.value))}>{Array.from({ length: 11 }, (_, index) => index + 2).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label>Interval in weeks<select data-testid="series-interval" value={intervalWeeks} disabled={attempt?.status === "sending" || attempt?.status === "uncertain"} onChange={(event) => setIntervalWeeks(Number(event.target.value))}>{[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      </div>
      {attempt?.status === "uncertain" && <p className="message message-warning" role="status" data-testid="series-uncertain">{attempt.message} {pendingAnchor && pendingAnchor !== reservation.reference ? `Original anchor: ${pendingAnchor}.` : ""}</p>}
      {error && <p id="series-create-error" className="message message-error" role="alert" data-testid="series-create-error">{error}</p>}
      {success && <p className="message message-success" role="status" data-testid="series-success">{success}</p>}
      <button className="button button-primary" data-testid="series-create" type="submit" disabled={attempt?.status === "sending"} aria-describedby={error ? "series-create-error" : undefined}>{attempt?.status === "sending" ? "Creating agreement…" : attempt?.status === "uncertain" ? "Retry same agreement" : "Create recurring visits"}</button>
    </form>}
    {hasSeries && series && <>
      <p className="series-meta" data-testid="series-summary">Agreement {series.series_id} · revision {series.revision} · every {series.interval_weeks} {series.interval_weeks === 1 ? "week" : "weeks"}</p>
      <ol className="series-occurrences" data-testid="series-occurrences">
        {series.occurrences.map((occurrence) => <li key={occurrence.index} data-testid={`series-occurrence-${occurrence.index}`}>
          <div><strong>Visit {occurrence.index + 1}</strong><span>{occurrence.reservation.starts_at_local.replace("T", " · ")} · {tableLabel(tableIds(occurrence.reservation), restaurant)}</span><span>{occurrence.reservation.reference} · {occurrence.reservation.status}{occurrence.exception ? " · changed independently" : ""}</span></div>
          <a className="button button-outline" href={`/lookup?reference=${encodeURIComponent(occurrence.reference)}&series_id=${encodeURIComponent(series.series_id)}`}>View booking</a>
          {occurrence.exception && <span className="status-pill" data-testid={`series-exception-${occurrence.index}`}>Changed independently</span>}
          {occurrence.reservation.status === "confirmed" && <button className="button button-outline" type="button" data-testid={`series-cancel-${occurrence.index}`} disabled={Boolean(cancelling)} onClick={() => void cancelOccurrence(occurrence.reference)}>{cancelling === occurrence.reference ? "Cancelling…" : "Cancel occurrence"}</button>}
          {cancelError && cancelErrorReference === occurrence.reference && <p className="message message-error" role="alert" data-testid={`series-cancel-error-${occurrence.index}`}>{cancelError}</p>}
        </li>)}
      </ol>
    </>}
  </section>;
}

function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const signup = mode === "signup";
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (error) revealFeedback(errorRef.current); }, [error]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    const form = new FormData(event.currentTarget);
    const body = Object.fromEntries(form.entries());
    try {
      const result = await api<{ token: string; display_name: string }>(signup ? "/auth/signup" : "/auth/login", { method: "POST", body: JSON.stringify(body) });
      storeAuth(result);
      const next = safeNext();
      window.location.assign(next);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "We could not complete sign in.");
    } finally { setBusy(false); }
  };
  return <main className="page-shell auth-page">
    <section className="auth-art"><img src={signup ? "/assets/signup-table.png" : "/assets/signin-bistro.png"} alt={signup ? "A table being prepared for a shared meal" : "A warmly lit restaurant ready for guests"} /><div><p className="eyebrow">Make a little room</p><h1>{signup ? "Gather around." : "Good to see you."}</h1><p>{signup ? "Create an account to keep your plans together." : "Sign in to keep your table plans close."}</p></div></section>
    <section className="auth-card" aria-labelledby="auth-title">
      <a className="back-link" href="/">← Back to search</a>
      <p className="eyebrow">Your Tablekeeper account</p><h2 id="auth-title">{signup ? "Create your account" : "Welcome back"}</h2><p className="auth-intro">{signup ? "A few details, then you’re ready to book." : "Sign in to manage your reservations."}</p>
      <form onSubmit={submit} data-testid={signup ? "signup-form" : "login-form"}>
        {signup && <label>Your name<input name="display_name" autoComplete="name" data-testid="signup-display-name" required /></label>}
        <label>Email address<input name="email" type="email" autoComplete="email" data-testid={signup ? "signup-email" : "login-email"} required /></label>
        <label>Password<input name="password" type="password" autoComplete={signup ? "new-password" : "current-password"} minLength={signup ? 8 : undefined} data-testid={signup ? "signup-password" : "login-password"} required /></label>
        <button className="button button-primary auth-submit" data-testid={signup ? "signup-submit" : "login-submit"} type="submit" disabled={busy}>{busy ? "Please wait…" : signup ? "Create account" : "Sign in"}<span aria-hidden="true">↗</span></button>
        {error && <p ref={errorRef} className="message message-error auth-feedback" role="alert" tabIndex={-1} data-testid="auth-error">{error}</p>}
        {notice && <p className="message message-success" role="status">{notice}</p>}
      </form>
      <p className="auth-switch">{signup ? "Already have an account?" : "New to Tablekeeper?"} <a href={signup ? "/login" : "/signup"}>{signup ? "Sign in" : "Create an account"}</a></p>
    </section>
  </main>;
}

function LookupPage({ signedIn }: { signedIn: boolean }) {
  const initialReference = new URLSearchParams(location.search).get("reference") || "";
  const [reference, setReference] = useState(initialReference);
  const [reservation, setReservation] = useState<Reservation | null>(null);
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [decision, setDecision] = useState<ReservationDecision | null>(null);
  const [decisionError, setDecisionError] = useState("");
  const [lookupError, setLookupError] = useState("");
  const [cancelError, setCancelError] = useState("");
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const lookup = async (event?: FormEvent) => {
    event?.preventDefault();
    setLookupError(""); setCancelError(""); setReservation(null); setRestaurant(null); setDecision(null); setDecisionError("");
    if (!signedIn) { setLookupError("Sign in to look up your reservation."); return; }
    if (!reference.trim()) { setLookupError("Enter your reservation reference."); return; }
    setBusy(true);
    try {
      const result = await api<Reservation>(`/reservations/${encodeURIComponent(reference.trim())}`);
      let detail: Restaurant | null = null;
      try { detail = await api<Restaurant>(`/restaurants/${encodeURIComponent(result.restaurant_id)}`); } catch { /* reservation facts remain available */ }
      setRestaurant(detail);
      setReservation(result);
      try { setDecision(await api<ReservationDecision>(`/reservations/${encodeURIComponent(result.reference)}/decision`)); }
      catch (failure) { setDecisionError(failure instanceof Error ? failure.message : "Current accepted terms could not be refreshed."); }
    } catch (failure) { setLookupError(failure instanceof Error ? failure.message : "The reservation could not be found."); }
    finally { setBusy(false); }
  };
  const cancel = async () => {
    if (!reservation || cancelling) return;
    setCancelError(""); setCancelling(true);
    try {
      const result = await api<Reservation>(`/reservations/${encodeURIComponent(reservation.reference)}/cancel`, { method: "POST" });
      setReservation(result);
      try { setDecision(await api<ReservationDecision>(`/reservations/${encodeURIComponent(reservation.reference)}/decision`)); }
      catch (failure) { setDecisionError(failure instanceof Error ? failure.message : "Current accepted terms could not be refreshed."); }
    } catch (failure) {
      setCancelError(failure instanceof Error ? `${failure.message} Check the reservation status before trying again.` : "Cancellation could not be confirmed. Check the reservation status before trying again.");
    } finally { setCancelling(false); }
  };

  return <main className="page-shell lookup-page">
    <section className="lookup-intro"><p className="eyebrow">Keep your plans close</p><h1>Your reservation,<br /><em>at a glance.</em></h1><p>Look up a reservation by its reference, then review its current status.</p><img src="/assets/restaurant-illustration.png" alt="A restaurant table ready for a meal" /></section>
    <section className="lookup-card" aria-labelledby="lookup-title">
      <p className="eyebrow">Reservation lookup</p><h2 id="lookup-title">Find a booking</h2><form onSubmit={lookup}>
        <label>Reservation reference<input data-testid="lookup-reference-input" value={reference} onChange={(event) => setReference(event.target.value)} autoComplete="off" required /></label>
        <button className="button button-primary" data-testid="lookup-submit" disabled={busy}>{busy ? "Looking it up…" : "Look up reservation"}<span aria-hidden="true">↗</span></button>
      </form>
      {!signedIn && <p className="message message-error" role="alert" data-testid="lookup-auth-error">Sign in to access your reservations. <a href="/login?next=%2Flookup">Sign in</a></p>}
      {lookupError && <p className="message message-error" role="alert" data-testid="reservation-error">{lookupError}</p>}
      {reservation && <article className="lookup-result" data-testid="reservation-detail" aria-live="polite">
        <div className="lookup-result-heading"><span className={`status-pill status-${reservation.status}`} data-testid="reservation-status">{reservation.status}</span><strong>{reservation.reference}</strong></div>
        <dl><div><dt>Restaurant</dt><dd>{restaurant?.name || reservation.restaurant_id}</dd></div><div><dt>Date &amp; time</dt><dd>{reservation.starts_at_local.replace("T", " · ")}</dd></div><div><dt>Guests</dt><dd>{reservation.party_size}</dd></div><div><dt>Table</dt><dd data-testid="reservation-tables">{tableLabel(tableIds(reservation), restaurant)}</dd></div></dl>
        {(decision?.revision ?? reservation.revision) !== undefined && <p className="revision-fact" data-testid="reservation-revision">Current revision {decision?.revision ?? reservation.revision}</p>}
        {(decision?.accepted_terms || reservation.accepted_terms) && <TermsSummary terms={(decision?.accepted_terms || reservation.accepted_terms)!} restaurant={restaurant} />}
        {decisionError && <p className="inline-status" role="status" data-testid="decision-error">Current terms refresh failed. Showing terms returned with this reservation. {decisionError}</p>}
        {reservation.status === "confirmed" && <button className="button button-outline cancel-button" data-testid="reservation-cancel-button" disabled={cancelling} onClick={cancel}>{cancelling ? "Cancelling…" : "Cancel reservation"}</button>}
        {reservation.status === "cancelled" && <p className="message message-success" role="status">This reservation is cancelled.</p>}
        <ReservationHistoryDisclosure key={reservation.reference} reference={reservation.reference} restaurant={restaurant} />
      {cancelError && <p className="message message-error" role="alert" data-testid="reservation-error">{cancelError}</p>}
      </article>}
      {reservation && signedIn && <SeriesPanel key={reservation.reference} reservation={reservation} restaurant={restaurant} />}
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
