# Requirements brief

Markdown copy of [context.docx](context.docx), the original task brief. It is the starting direction, not a fixed blueprint — see [architecture.md](architecture.md) for what we decided to build.

## Task: AI-powered salon booking system with voice agent

### Objective
Design and develop a complete salon appointment management system featuring an AI voice agent that interacts with customers, answers questions, checks real-time availability, and books, reschedules, or cancels appointments.

### Required technology stack
- AI voice agent: Retell AI
- Backend: Python FastAPI
- Database: PostgreSQL
- Frontend: React or Next.js with Tailwind CSS
- ORM and migrations: SQLAlchemy and Alembic
- Deployment: Docker

## Functional requirements

### 1. AI voice agent
- Create a natural, conversational salon receptionist using Retell AI.
- Answer questions about salon services, prices, opening hours, and staff.
- Collect the customer's name, phone number, preferred service, staff member (optional), date, and time.
- Check availability before offering appointment slots.
- Confirm all booking details with the customer before creating an appointment.
- Support booking, rescheduling, cancellation, and frequently asked questions.
- Integrate Retell custom functions with FastAPI endpoints.

### 2. Backend and booking logic
Implement the following APIs:

| Method | Path | Purpose |
|---|---|---|
| GET | `/services` | Retrieve salon services and prices |
| GET | `/staff` | Retrieve available staff members |
| POST | `/availability` | Find available appointment slots |
| POST | `/bookings` | Create an appointment |
| PATCH | `/bookings/{id}` | Reschedule an appointment |
| DELETE | `/bookings/{id}` | Cancel an appointment |
| GET | `/bookings` | Retrieve bookings with appropriate access controls |
| POST | `/webhooks/retell` | Receive and process Retell call events |

The backend must validate business hours, service duration, staff availability, booking conflicts, and cancellation rules. Prevent double bookings, including when multiple customers request the same slot simultaneously.

### 3. PostgreSQL database
Design appropriate tables for:
- Customers
- Services and prices
- Staff members and their working schedules
- Appointments and booking statuses
- Call logs and conversation summaries

Use database transactions, appropriate constraints, and secure data handling to maintain booking consistency.

### 4. Modern admin dashboard
A responsive, professional dashboard featuring:
- Overview cards for today's appointments, upcoming bookings, and cancellations.
- Calendar views for daily, weekly, and monthly appointments.
- Booking creation, editing, rescheduling, and cancellation.
- Staff management, working hours, and availability.
- Service management, prices, and durations.
- Customer records and appointment history.
- Voice-call logs, transcripts where available, booking outcomes, and call analytics.
- Search, filtering, and status indicators.

Implement authentication and role-based access for salon administrators and staff.

## Expected deliverables
- Fully functional frontend, backend, and PostgreSQL database.
- Working Retell voice agent connected to real booking APIs.
- Complete appointment lifecycle and conflict prevention.
- Responsive dashboard with authentication.
- API documentation, database schema, and setup instructions.
- Docker-based deployment configuration and a GitHub repository.
- Demonstration video showing successful booking, rescheduling, cancellation, and conflict handling.

## Evaluation criteria

| Area | Weight |
|---|---|
| Voice-agent quality and correct tool usage | 20% |
| Booking logic and conflict prevention | 25% |
| Backend and database design | 20% |
| Dashboard UI/UX | 20% |
| Testing, security, documentation, and deployment | 15% |

> **Important:** The voice agent must never claim that an appointment is booked, changed, or cancelled unless the backend confirms that the operation succeeded. All booking operations must use the PostgreSQL database as the source of truth.
