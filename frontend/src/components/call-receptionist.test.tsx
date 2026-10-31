import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";

const token = vi.fn();
const toastError = vi.fn();
type Handler = () => void;
const handlers: Record<string, Handler> = {};
const fakeCall = {
  on: (event: string, handler: Handler) => {
    handlers[event] = handler;
  },
  mute: vi.fn(),
  disconnect: vi.fn(() => handlers.disconnect?.()),
};
const connect = vi.fn(async () => fakeCall);
const destroy = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { twilio: { token: () => token() } } };
});
vi.mock("sonner", () => ({ toast: { error: (message: string) => toastError(message) } }));
vi.mock("@twilio/voice-sdk", () => ({
  Device: vi.fn(function Device() {
    return { connect, destroy };
  }),
}));

import { CallReceptionist } from "./call-receptionist";

function renderButton() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CallReceptionist />
    </QueryClientProvider>,
  );
}

describe("CallReceptionist", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(handlers)) delete handlers[key];
  });

  it("places a call, shows its progress, mutes and hangs up", async () => {
    token.mockResolvedValue({ token: "jwt", identity: "dashboard-1", expires_in: 3600 });
    renderButton();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Call the receptionist" })));
    expect(connect).toHaveBeenCalledOnce();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();

    act(() => handlers.ringing());
    expect(screen.getByText("Ringing…")).toBeInTheDocument();
    act(() => handlers.accept());
    expect(screen.getByText(/On the call · 0:00/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mute" }));
    expect(fakeCall.mute).toHaveBeenCalledWith(true);
    expect(screen.getByRole("button", { name: "Unmute" })).toHaveAttribute("aria-pressed", "true");

    act(() => fireEvent.click(screen.getByRole("button", { name: "Hang up" })));
    expect(destroy).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Call the receptionist" })).toBeInTheDocument();
  });

  it("explains when browser calling is not set up on the server", async () => {
    token.mockRejectedValue(new ApiError(503, "browser_calling_not_configured", "off"));
    renderButton();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Call the receptionist" })));
    expect(toastError).toHaveBeenCalledWith("Browser calling isn't set up on the server yet.");
    expect(connect).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Call the receptionist" })).toBeInTheDocument();
  });
});
