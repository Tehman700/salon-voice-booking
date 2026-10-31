import type {
  Booking,
  BookingStatus,
  Business,
  CallLog,
  CallOutcome,
  Location,
  Service,
  Staff,
  TimeOff,
  User,
  WorkingHours,
} from "@/lib/api/types";

/** Mock records carry the tenant id the real backend derives from the token. */
type Tenant = { business_id: string };

export type MockUser = User & Tenant & { password: string };
export type MockCustomer = Tenant & {
  id: string;
  full_name: string;
  phone: string;
  email: string | null;
  notes: string | null;
  created_at: string;
};

export type MockDb = {
  businesses: Business[];
  locations: (Location & Tenant)[];
  users: MockUser[];
  services: (Service & Tenant)[];
  staff: (Staff & Tenant)[];
  hours: Record<string, WorkingHours>;
  timeOff: (TimeOff & Tenant)[];
  customers: MockCustomer[];
  bookings: (Booking & Tenant)[];
  calls: (CallLog & Tenant)[];
  refreshTokens: Record<string, string>;
};

export const DEMO_PASSWORD = "demo-password";
export const DEMO_USERS = {
  owner: "owner@lumiere.pk",
  staff: "sana@lumiere.pk",
  single: "owner@studionoor.pk",
} as const;

const PKT_OFFSET_HOURS = 5; // Asia/Karachi, no DST

/** Small deterministic PRNG so the seed is stable within a day. */
function prng(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** IDs are UUIDs, as in the contract. */
export function mockId(): string {
  return crypto.randomUUID();
}

/** UTC ISO string for a Karachi-local wall-clock time `dayOffset` days from today. */
function pktIso(dayOffset: number, hour: number, minute = 0): string {
  const now = new Date();
  const local = new Date(now.getTime() + PKT_OFFSET_HOURS * 3600_000);
  const d = Date.UTC(
    local.getUTCFullYear(),
    local.getUTCMonth(),
    local.getUTCDate() + dayOffset,
    hour - PKT_OFFSET_HOURS,
    minute,
  );
  return new Date(d).toISOString().replace(".000Z", "Z");
}

function addMinutes(iso: string, minutes: number): string {
  return new Date(new Date(iso).getTime() + minutes * 60_000).toISOString().replace(".000Z", "Z");
}

const REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
export function makeReference(rand: () => number = Math.random): string {
  return Array.from({ length: 5 }, () => REFERENCE_ALPHABET[Math.floor(rand() * REFERENCE_ALPHABET.length)]).join("");
}

const STANDARD_HOURS: WorkingHours = [0, 1, 2, 3, 4, 5].map((weekday) => ({
  weekday: weekday as 0 | 1 | 2 | 3 | 4 | 5,
  start: "10:00",
  end: "20:00",
}));

const CUSTOMER_NAMES = [
  "Ayesha Khan", "Fatima Malik", "Hira Qureshi", "Zainab Ahmed", "Mahnoor Iqbal", "Areeba Siddiqui",
  "Sara Hussain", "Noor Fatima", "Amna Raza", "Maryam Javed", "Iqra Butt", "Komal Sheikh",
  "Rabia Anwar", "Sana Mirza", "Laiba Chaudhry", "Hamza Ali", "Usman Tariq", "Bilal Rehman",
  "Danish Aslam", "Ahmed Farooq", "Mehwish Nadeem", "Kiran Abbas",
];

function buildLumiere(db: MockDb, rand: () => number) {
  const businessId = mockId();
  db.businesses.push({
    id: businessId,
    name: "Lumière Salon",
    slug: "lumiere-salon",
    location_mode: "multiple",
    default_timezone: "Asia/Karachi",
    cancellation_window_minutes: 120,
  });

  const gulberg = mockId();
  const dha = mockId();
  db.locations.push(
    {
      business_id: businessId, id: gulberg, slug: "gulberg", name: "Gulberg", timezone: "Asia/Karachi",
      phone: "+924235761234", address_line1: "45-B Main Boulevard", city: "Lahore", country: "PK",
      is_active: true, cancellation_window_minutes: null, effective_cancellation_window_minutes: 120,
    },
    {
      business_id: businessId, id: dha, slug: "dha-phase-5", name: "DHA Phase 5", timezone: "Asia/Karachi",
      phone: "+924235769876", address_line1: "112 CCA, Sector B", city: "Lahore", country: "PK",
      is_active: true, cancellation_window_minutes: 240, effective_cancellation_window_minutes: 240,
    },
  );

  const services: (Service & { business_id: string })[] = [
    ["Women's haircut", "Hair", 45, 15, 350000],
    ["Blow-dry", "Hair", 30, 10, 200000],
    ["Hair colour", "Colour", 120, 15, 1200000],
    ["Highlights", "Colour", 150, 15, 1650000],
    ["Keratin treatment", "Treatment", 180, 15, 2500000],
    ["Classic facial", "Skin", 60, 10, 450000],
    ["Manicure", "Nails", 45, 10, 250000],
    ["Bridal makeup", "Makeup", 120, 30, 4500000],
  ].map(([name, category, duration, buffer, price]) => ({
    business_id: businessId,
    id: mockId(),
    name: name as string,
    description: null,
    category: category as string,
    duration_minutes: duration as number,
    buffer_minutes: buffer as number,
    price_minor: price as number,
    currency: "PKR",
    is_active: true,
    location_overrides: [],
  }));
  services[7].location_overrides = [
    { location_id: dha, price_minor: 5000000, duration_minutes: null, is_offered: true },
  ];
  services[4].location_overrides = [
    { location_id: dha, price_minor: null, duration_minutes: null, is_offered: false },
  ];
  db.services.push(...services);
  const sid = (i: number) => services[i].id;

  const sanaUserId = mockId();
  const staff: (Staff & { business_id: string })[] = [
    { full_name: "Sana Iqbal", title: "Senior stylist", color: "#0070f3", location_id: gulberg, service_ids: [sid(0), sid(1), sid(2), sid(3)], user_id: sanaUserId },
    { full_name: "Mariam Shah", title: "Colourist", color: "#7928ca", location_id: gulberg, service_ids: [sid(2), sid(3), sid(4)], user_id: null },
    { full_name: "Hina Javed", title: "Skin specialist", color: "#29bc9b", location_id: gulberg, service_ids: [sid(5), sid(6)], user_id: null },
    { full_name: "Ali Raza", title: "Stylist", color: "#f5a623", location_id: dha, service_ids: [sid(0), sid(1), sid(4)], user_id: null },
    { full_name: "Nida Hassan", title: "Makeup artist", color: "#eb367f", location_id: dha, service_ids: [sid(7), sid(5)], user_id: null },
    { full_name: "Kamran Yousaf", title: "Junior stylist", color: "#4d4d4d", location_id: dha, service_ids: [sid(0), sid(1), sid(6)], user_id: null },
  ].map((s) => ({ ...s, business_id: businessId, id: mockId(), is_active: true }));
  db.staff.push(...staff);
  for (const s of staff) db.hours[s.id] = STANDARD_HOURS.map((h) => ({ ...h }));
  db.hours[staff[2].id] = STANDARD_HOURS.filter((h) => h.weekday !== 2).map((h) => ({ ...h }));

  db.timeOff.push({
    business_id: businessId, id: mockId(), staff_id: staff[1].id,
    starts_at: pktIso(9, 0), ends_at: pktIso(12, 0), reason: "Annual leave",
  });

  db.users.push(
    {
      business_id: businessId, id: mockId(), email: DEMO_USERS.owner, full_name: "Ayesha Raza",
      role: "owner", location_id: null, is_active: true, last_login_at: pktIso(-1, 18), password: DEMO_PASSWORD,
    },
    {
      business_id: businessId, id: sanaUserId, email: DEMO_USERS.staff, full_name: "Sana Iqbal",
      role: "staff", location_id: gulberg, is_active: true, last_login_at: pktIso(-2, 9), password: DEMO_PASSWORD,
    },
  );

  const customers: MockCustomer[] = CUSTOMER_NAMES.map((full_name, i) => ({
    business_id: businessId,
    id: mockId(),
    full_name,
    phone: `+92300${String(1234567 + i * 7919).slice(0, 7)}`,
    email: i % 3 === 0 ? `${full_name.split(" ")[0].toLowerCase()}@example.com` : null,
    notes: i === 2 ? "Prefers Sana. Sensitive scalp." : null,
    created_at: pktIso(-90 + i, 12),
  }));
  db.customers.push(...customers);

  // Bookings: two weeks back to two weeks ahead, per staff member.
  for (let day = -14; day <= 14; day++) {
    for (const member of staff) {
      let hour = 10 + Math.floor(rand() * 2);
      let minute = rand() < 0.5 ? 0 : 30;
      const perDay = day === 0 ? 4 : 1 + Math.floor(rand() * 3);
      for (let n = 0; n < perDay && hour < 19; n++) {
        const serviceId = member.service_ids[Math.floor(rand() * member.service_ids.length)];
        const service = services.find((s) => s.id === serviceId)!;
        const customer = customers[Math.floor(rand() * customers.length)];
        const startsAt = pktIso(day, hour, minute);
        const endsAt = addMinutes(startsAt, service.duration_minutes);
        const source = rand() < 0.55 ? "voice" : "dashboard";
        let status: BookingStatus = "booked";
        if (day < 0) {
          const r = rand();
          status = r < 0.78 ? "completed" : r < 0.92 ? "cancelled" : "no_show";
        } else if (rand() < 0.08) {
          status = "cancelled";
        }
        const createdAt = pktIso(Math.min(day, 0) - 1 - Math.floor(rand() * 5), 11);
        db.bookings.push({
          business_id: businessId,
          id: mockId(),
          reference: makeReference(rand),
          location_id: member.location_id,
          service_id: service.id,
          staff_id: member.id,
          customer: { id: customer.id, full_name: customer.full_name, phone: customer.phone, email: customer.email },
          starts_at: startsAt,
          ends_at: endsAt,
          status,
          source,
          call_id: null,
          price_minor: service.price_minor,
          currency: "PKR",
          notes: rand() < 0.15 ? "First visit" : null,
          created_at: createdAt,
          cancelled_at: status === "cancelled" ? addMinutes(createdAt, 600) : null,
          cancellation_reason: status === "cancelled" ? "Customer asked to cancel" : null,
        });
        const total = service.duration_minutes + service.buffer_minutes + (rand() < 0.5 ? 30 : 0);
        const next = hour * 60 + minute + Math.ceil(total / 30) * 30;
        hour = Math.floor(next / 60);
        minute = next % 60;
      }
    }
  }

  // Calls: the last ten days, linked to voice bookings where the outcome is "booked".
  const outcomes: CallOutcome[] = ["booked", "booked", "booked", "info_only", "info_only", "rescheduled", "cancelled", "abandoned", "failed"];
  const voiceBookings = db.bookings.filter((b) => b.business_id === businessId && b.source === "voice");
  for (let day = -9; day <= 0; day++) {
    const count = 2 + Math.floor(rand() * 4);
    for (let n = 0; n < count; n++) {
      const outcome = outcomes[Math.floor(rand() * outcomes.length)];
      const startedAt = pktIso(day, 9 + Math.floor(rand() * 10), Math.floor(rand() * 60));
      const duration = outcome === "abandoned" ? 8 + Math.floor(rand() * 15) : 60 + Math.floor(rand() * 180);
      const customer = customers[Math.floor(rand() * customers.length)];
      const location = rand() < 0.6 ? gulberg : dha;
      const linked = outcome === "booked" ? voiceBookings.find((b) => !b.call_id && b.location_id === location) : undefined;
      const callId = mockId();
      if (linked) linked.call_id = callId;
      db.calls.push({
        business_id: businessId,
        id: callId,
        retell_call_id: `call_${Math.floor(rand() * 1e12).toString(36)}`,
        location_id: location,
        from_number: customer.phone,
        started_at: startedAt,
        ended_at: addMinutes(startedAt, Math.ceil(duration / 60)),
        duration_seconds: duration,
        outcome,
        summary: summaryFor(outcome, customer.full_name),
        transcript: outcome === "abandoned" ? [{ role: "agent", text: "Thanks for calling Lumière Salon, how can I help?" }] : transcriptFor(outcome),
        booking_id: linked?.id ?? null,
      });
    }
  }
}

function summaryFor(outcome: CallOutcome, name: string): string {
  switch (outcome) {
    case "booked": return `${name} booked an appointment after checking availability.`;
    case "rescheduled": return `${name} moved their appointment to a later slot.`;
    case "cancelled": return `${name} cancelled their upcoming appointment.`;
    case "info_only": return `${name} asked about opening hours and prices.`;
    case "failed": return `The agent could not complete the request; the caller was offered a callback.`;
    case "abandoned": return `The caller hung up before stating a request.`;
  }
}

function transcriptFor(outcome: CallOutcome): CallLog["transcript"] {
  const opening = [
    { role: "agent" as const, text: "Thanks for calling Lumière Salon, how can I help?" },
  ];
  if (outcome === "info_only") {
    return [
      ...opening,
      { role: "user", text: "Hi, what time do you close on Saturday?" },
      { role: "agent", text: "We're open until 8 pm on Saturdays. A women's haircut starts at Rs 3,500." },
      { role: "user", text: "Great, thanks." },
    ];
  }
  if (outcome === "failed") {
    return [
      ...opening,
      { role: "user", text: "I want to book a bridal trial with two artists at once." },
      { role: "agent", text: "I can't book two artists together, but I can ask the salon to call you back. Is that okay?" },
      { role: "user", text: "Yes please." },
    ];
  }
  return [
    ...opening,
    { role: "user", text: "I'd like a haircut tomorrow afternoon, please." },
    { role: "agent", text: "Sana has 3:30 pm free tomorrow at Gulberg. Shall I book that?" },
    { role: "user", text: "Yes, that works." },
    { role: "agent", text: "Done. Your booking reference is K7Q2M. You'll get a confirmation shortly." },
  ];
}

function buildStudioNoor(db: MockDb, rand: () => number) {
  const businessId = mockId();
  db.businesses.push({
    id: businessId, name: "Studio Noor", slug: "studio-noor", location_mode: "single",
    default_timezone: "Asia/Karachi", cancellation_window_minutes: 120,
  });
  const locationId = mockId();
  db.locations.push({
    business_id: businessId, id: locationId, slug: "studio-noor", name: "Studio Noor", timezone: "Asia/Karachi",
    phone: "+922135871234", address_line1: "Shop 4, Zamzama Boulevard", city: "Karachi", country: "PK",
    is_active: true, cancellation_window_minutes: null, effective_cancellation_window_minutes: 120,
  });
  const service = {
    business_id: businessId, id: mockId(), name: "Haircut", description: null, category: "Hair",
    duration_minutes: 45, buffer_minutes: 15, price_minor: 300000, currency: "PKR", is_active: true, location_overrides: [],
  };
  db.services.push(service);
  const member = {
    business_id: businessId, id: mockId(), location_id: locationId, user_id: null, full_name: "Noor Ahmed",
    title: "Owner stylist", color: "#0070f3", service_ids: [service.id], is_active: true,
  };
  db.staff.push(member);
  db.hours[member.id] = STANDARD_HOURS.map((h) => ({ ...h }));
  db.users.push({
    business_id: businessId, id: mockId(), email: DEMO_USERS.single, full_name: "Noor Ahmed",
    role: "owner", location_id: null, is_active: true, last_login_at: null, password: DEMO_PASSWORD,
  });
  const customer: MockCustomer = {
    business_id: businessId, id: mockId(), full_name: "Zara Kazmi", phone: "+923331234567",
    email: null, notes: null, created_at: pktIso(-20, 12),
  };
  db.customers.push(customer);
  for (const day of [-3, 0, 2]) {
    const startsAt = pktIso(day, 14);
    db.bookings.push({
      business_id: businessId, id: mockId(), reference: makeReference(rand), location_id: locationId,
      service_id: service.id, staff_id: member.id,
      customer: { id: customer.id, full_name: customer.full_name, phone: customer.phone, email: null },
      starts_at: startsAt, ends_at: addMinutes(startsAt, 45), status: day < 0 ? "completed" : "booked",
      source: "dashboard", call_id: null, price_minor: 300000, currency: "PKR", notes: null,
      created_at: pktIso(day - 2, 10), cancelled_at: null, cancellation_reason: null,
    });
  }
}

export function createSeed(): MockDb {
  const db: MockDb = {
    businesses: [], locations: [], users: [], services: [], staff: [], hours: {}, timeOff: [],
    customers: [], bookings: [], calls: [], refreshTokens: {},
  };
  const rand = prng(20261028);
  buildLumiere(db, rand);
  buildStudioNoor(db, rand);
  return db;
}
