import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type RestaurantSummary = { id: string; name: string; timezone: string };
type Opening = { weekday: string; opens: string; closes: string };
type Table = { id: string; label: string; capacity: number };
type Restaurant = RestaurantSummary & {
  opening_hours: Opening[];
  tables: Table[];
  combinable: string[][];
  slot_minutes: number;
  reservation_duration_minutes: number;
};
type AvailableOption = { table_ids: string[]; capacity: number };
type Slot = {
  starts_at_local: string;
  starts_at: string;
  available_table_ids: string[];
  available_options: AvailableOption[];
};
type Availability = { restaurant_id: string; date: string; timezone: string; slots: Slot[] };
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
};
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
const WEEKDAYS = [
  { key: "mon", label: "Monday" }, { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" }, { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" }, { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
];

function token() { return localStorage.getItem(AUTH_TOKEN); }
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
    const draft = { restaurantId, date, party, bookingParty, selected };
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  }, [restaurantId, date, party, bookingParty, selected]);
  useEffect(() => { if (attempt) sessionStorage.setItem(ATTEMPT_KEY, JSON.stringify(attempt)); }, [attempt]);

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

  const runSearch = async (event?: FormEvent, clearSelection = true, force = false) => {
    event?.preventDefault();
    if (!restaurant || !date || party < 1 || (!force && (attempt?.status === "uncertain" || attempt?.status === "sending"))) return;
    const sequence = ++searchSequence.current;
    setSearching(true);
    setSearchError("");
    setAvailability(null);
    if (clearSelection) { setSelected(null); setAuthError(false); }
    try {
      const query = new URLSearchParams({ restaurant_id: restaurant.id, date, party_size: String(party) });
      const result = await api<Availability>(`/availability?${query}`);
      if (sequence === searchSequence.current) setAvailability(result);
    } catch (error) {
      if (sequence === searchSequence.current) setSearchError(error instanceof Error ? error.message : "Availability could not be loaded.");
    } finally {
      if (sequence === searchSequence.current) setSearching(false);
    }
  };

  const setSearchField = () => { searchSequence.current += 1; setAvailability(null); setSearchError(""); };
  const refreshAvailability = () => runSearch(undefined, false, true);
  const choose = (value: Selected) => {
    if (attempt?.status === "uncertain" || attempt?.status === "sending") return;
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
  const currentBody = selected && restaurant ? {
    restaurant_id: restaurant.id,
    ...(selected.tableIds.length === 1 ? { table_id: selected.tableIds[0] } : { table_ids: selected.tableIds }),
    starts_at_local: selected.startsAtLocal,
    party_size: Number(bookingParty),
  } : null;

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
          {options.map((option) => <section className="table-group" key={option.ids.join("+")} aria-label={option.label}>
            <div className="table-group-label"><img src="/assets/picnic-table.svg" alt="" /><div><strong>{option.label}</strong><small>Up to {option.capacity} guests</small></div></div>
            <div className="time-cells">{availability.slots.map((slot) => {
              const time = slot.starts_at_local.slice(11, 16);
              const isAvailable = slot.available_options?.some((available) => available.table_ids.join("+") === option.ids.join("+")) || (option.ids.length === 1 && slot.available_table_ids.includes(option.ids[0]));
              const isSelected = selected?.tableIds.join("+") === option.ids.join("+") && selected.startsAtLocal === slot.starts_at_local;
              return <button key={slot.starts_at_local} type="button" className={`time-cell${isSelected ? " is-selected" : ""}`} data-testid={`slot-${option.ids.join("+")}-${time}`} data-available={String(isAvailable)} aria-label={`${option.label}, ${time}, ${isAvailable ? "available" : "unavailable"}`} aria-pressed={isSelected} title={isAvailable ? `Select ${time}` : "Unavailable"} disabled={!isAvailable || locked} onClick={() => choose({ tableIds: option.ids, startsAtLocal: slot.starts_at_local })}>{time}</button>;
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
          <label className="booking-party-field">Party size<input data-testid="booking-party-size" type="number" min="1" step="1" value={bookingParty} disabled={locked} onChange={(event) => setBookingParty(Number(event.target.value))} required /></label>
          {!signedIn && <><a className="button button-outline sign-in-action" href="/login?next=%2F">Sign in</a>{authError && <p id="auth-error" className="message message-error auth-panel-error" role="alert" tabIndex={-1} data-testid="auth-error">Please sign in before completing your reservation. Your table selection is saved.</p>}</>}
          {restoreError && <p className="message message-error" role="alert">{restoreError}</p>}
          {attempt?.status === "uncertain" && <p className="message message-warning" role="status" data-testid="booking-uncertain">{attempt.message}</p>}
          {attempt?.status === "rejected" && <p className="message message-error" role="alert" data-testid="booking-error">{attempt.message}</p>}
          {attempt?.status === "confirmed" && attempt.receipt && currentBody && JSON.stringify(attempt.body) === JSON.stringify(currentBody) && <div className="receipt" role="status" data-testid="confirmation"><span className="receipt-kicker">Reservation confirmed</span><strong data-testid="confirmation-reference">{attempt.receipt.reference}</strong><span data-testid="confirmation-details">{restaurants.find((item) => item.id === attempt.receipt?.restaurant_id)?.name || attempt.receipt.restaurant_id} · {tableLabel(tableIds(attempt.receipt), restaurant)} · {attempt.receipt.starts_at_local.replace("T", " ")}</span><span data-testid="confirmation-tables">{tableLabel(tableIds(attempt.receipt), restaurant)}</span></div>}
          <button className="button button-primary review-submit" data-testid="booking-submit" type="submit" disabled={!selected || attempt?.status === "sending"} aria-describedby={authError ? "auth-error" : undefined}>{attempt?.status === "sending" ? "Saving your table…" : attempt?.status === "uncertain" ? "Retry reservation" : "Reserve this table"}<span aria-hidden="true">↗</span></button>
          <p className="review-caption">Nothing is held until the reservation is confirmed.</p>
        </form>
      </> : <div className="review-empty"><span className="review-icon"><img src="/assets/tools-kitchen-2.svg" alt="" /></span><p>Select an available time to review your reservation here.</p><small>Your date, party size and chosen table stay together.</small></div>}
    </section>
  </main>;
}

function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const signup = mode === "signup";
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
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
        {error && <p className="message message-error" role="alert" data-testid="auth-error">{error}</p>}
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
  const [lookupError, setLookupError] = useState("");
  const [cancelError, setCancelError] = useState("");
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const lookup = async (event?: FormEvent) => {
    event?.preventDefault();
    setLookupError(""); setCancelError(""); setReservation(null); setRestaurant(null);
    if (!signedIn) { setLookupError("Sign in to look up your reservation."); return; }
    if (!reference.trim()) { setLookupError("Enter your reservation reference."); return; }
    setBusy(true);
    try {
      const result = await api<Reservation>(`/reservations/${encodeURIComponent(reference.trim())}`);
      let detail: Restaurant | null = null;
      try { detail = await api<Restaurant>(`/restaurants/${encodeURIComponent(result.restaurant_id)}`); } catch { /* reservation facts remain available */ }
      setRestaurant(detail);
      setReservation(result);
    } catch (failure) { setLookupError(failure instanceof Error ? failure.message : "The reservation could not be found."); }
    finally { setBusy(false); }
  };
  const cancel = async () => {
    if (!reservation || cancelling) return;
    setCancelError(""); setCancelling(true);
    try {
      const result = await api<Reservation>(`/reservations/${encodeURIComponent(reservation.reference)}/cancel`, { method: "POST" });
      setReservation(result);
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
        {reservation.status === "confirmed" && <button className="button button-outline cancel-button" data-testid="reservation-cancel-button" disabled={cancelling} onClick={cancel}>{cancelling ? "Cancelling…" : "Cancel reservation"}</button>}
        {reservation.status === "cancelled" && <p className="message message-success" role="status">This reservation is cancelled.</p>}
      {cancelError && <p className="message message-error" role="alert" data-testid="reservation-error">{cancelError}</p>}
      </article>}
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
