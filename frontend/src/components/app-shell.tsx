"use client";

import {
  CalendarDays,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  PhoneCall,
  Scissors,
  Settings,
  Sun,
  UserCog,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useTheme } from "@/components/theme-provider";
import type { Role } from "@/lib/api";
import { useAuth, useMe } from "@/lib/auth";
import { initials, ROLE_LABEL } from "@/lib/format";
import { ALL, LocationScopeProvider, useLocationScope } from "@/lib/location-scope";

type NavItem = { href: string; label: string; icon: typeof LayoutDashboard; roles: Role[] };

const ALL_ROLES: Role[] = ["owner", "manager", "staff", "platform_admin"];
const MANAGERS: Role[] = ["owner", "manager", "platform_admin"];

const NAV: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard, roles: MANAGERS },
  { href: "/calendar", label: "Calendar", icon: CalendarDays, roles: ALL_ROLES },
  { href: "/bookings", label: "Bookings", icon: ListChecks, roles: ALL_ROLES },
  { href: "/customers", label: "Customers", icon: Users, roles: MANAGERS },
  { href: "/staff", label: "Staff", icon: UserCog, roles: MANAGERS },
  { href: "/services", label: "Services", icon: Scissors, roles: MANAGERS },
  { href: "/calls", label: "Voice calls", icon: PhoneCall, roles: MANAGERS },
  { href: "/team", label: "Team", icon: Users, roles: MANAGERS },
  { href: "/settings", label: "Settings", icon: Settings, roles: ["owner", "platform_admin"] },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/** Signs in first, then renders the shell. Everything below this can assume a signed-in user. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return (
      <div className="flex flex-1 items-center justify-center p-8" role="status" aria-label="Loading">
        <div className="w-full max-w-sm space-y-3">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-24 w-full" />
        </div>
      </div>
    );
  }

  return (
    <LocationScopeProvider>
      <ShellFrame>{children}</ShellFrame>
    </LocationScopeProvider>
  );
}

function ShellFrame({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const pathname = usePathname();
  const router = useRouter();
  const items = NAV.filter((item) => item.roles.includes(me.role));
  const allowed = items.some((item) => isActive(pathname, item.href));

  // Staff land on the calendar; anyone opening a page their role can't use is sent to a page they can.
  useEffect(() => {
    if (!allowed && items[0]) router.replace(items[0].href === "/" ? "/" : items[0].href);
  }, [allowed, items, router]);

  return (
    <div className="flex min-h-screen flex-1">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-card md:flex">
        <Brand />
        <Nav items={items} />
        <div className="mt-auto border-t p-3 text-xs text-muted-foreground">
          <span className="font-mono uppercase">{me.business?.name}</span>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar items={items} />
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 sm:p-6">{allowed ? children : null}</main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex h-14 items-center gap-2 border-b px-4">
      <span className="flex size-7 items-center justify-center rounded-md bg-primary font-mono text-xs text-primary-foreground">
        SV
      </span>
      <span className="font-semibold tracking-tight">Salon Voice</span>
    </div>
  );
}

function Nav({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5 p-3">
      {items.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`relative flex h-9 items-center gap-2.5 rounded-md px-3 text-sm transition-colors ${
              active
                ? "bg-muted font-medium text-foreground before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-primary"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            }`}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function TopBar({ items }: { items: NavItem[] }) {
  const me = useMe();
  const { logout } = useAuth();
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const { locations, selected, select, isMulti } = useLocationScope();
  const [open, setOpen] = useState(false);

  async function signOut() {
    await logout();
    router.replace("/login");
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur sm:px-6">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation">
            <Menu className="size-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-64 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Pages of the dashboard</SheetDescription>
          <Brand />
          <Nav items={items} onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      {isMulti && (
        <Select value={selected} onValueChange={select}>
          <SelectTrigger className="w-[200px]" aria-label="Location">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {me.role !== "staff" && me.role !== "manager" && <SelectItem value={ALL}>All locations</SelectItem>}
            {locations.map((l) => (
              <SelectItem key={l.id} value={l.id}>
                {l.name}
                {!l.is_active && " (inactive)"}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <div className="ml-auto flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle dark mode"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          <Sun className="size-4 dark:hidden" />
          <Moon className="hidden size-4 dark:block" />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="gap-2 px-2">
              <Avatar className="size-7" aria-hidden="true">
                <AvatarFallback className="text-xs">{initials(me.full_name)}</AvatarFallback>
              </Avatar>
              <span className="sr-only">Account menu</span>
              <span className="hidden text-sm sm:inline">{me.full_name}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>
              <div className="text-sm font-medium">{me.full_name}</div>
              <div className="text-xs font-normal text-muted-foreground">{me.email}</div>
              <div className="mt-1 font-mono text-[11px] font-normal uppercase text-muted-foreground">
                {ROLE_LABEL[me.role]}
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={signOut}>
              <LogOut className="size-4" /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
