export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-screen flex-1 items-center justify-center overflow-hidden bg-background p-4">
      {/* The brand mesh gradient: hero/auth screens only, never inside the app. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-60 dark:opacity-30">
        <div className="absolute -left-24 -top-24 size-[480px] rounded-full bg-[#007cf0] blur-[120px]" />
        <div className="absolute -right-24 top-10 size-[420px] rounded-full bg-[#ff0080] blur-[130px]" />
        <div className="absolute bottom-[-120px] left-1/3 size-[420px] rounded-full bg-[#f9cb28] blur-[130px]" />
        <div className="absolute bottom-0 right-1/4 size-[320px] rounded-full bg-[#50e3c2] blur-[120px]" />
      </div>
      <div className="relative w-full max-w-md">{children}</div>
    </div>
  );
}
