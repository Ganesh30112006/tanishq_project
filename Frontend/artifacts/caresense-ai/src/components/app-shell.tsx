/**
 * The signed-in frame: a floating navigation dock, a slim top bar with
 * breadcrumbs and a command palette, and a mobile tab bar.
 *
 * Navigation is filtered by permission - an entry only renders when the
 * signed-in user holds one of its codes. The server still authorises every
 * request; this only stops offering controls a role cannot use.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useLocation } from 'wouter';
import {
  Bell, ChevronsLeft, ChevronsRight, CircleHelp, FileText, LayoutDashboard, LogOut, Menu, Search,
  Settings2, ShieldCheck, ShieldHalf, Upload, UserRound, X,
} from 'lucide-react';
import { getListNotificationsQueryKey, useListNotifications } from '@workspace/api-client-react';
import type { Notification } from '@workspace/api-client-react';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator, CommandShortcut } from '@/components/ui/command';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { BrandMark, OfflineBanner } from '@/components/error-page';
import { Modal } from '@/components/ui-kit';
import { PERM, useAuth } from '@/lib/auth';
import { initialsOf, isPatientView, primaryRole, ROLE_LABEL } from '@/lib/display';
import { requestUpload } from '@/lib/upload-intent';

type NavItem = { href: string; label: string; icon: typeof LayoutDashboard; anyPerm?: string[]; group: 'health' | 'manage' };

const NAV_ITEMS: NavItem[] = [
  { href: '/', label: 'Overview', icon: LayoutDashboard, group: 'health' },
  { href: '/patients', label: 'Patients', icon: UserRound, anyPerm: [PERM.PATIENT_READ_OWN], group: 'health' },
  { href: '/reports', label: 'Reports', icon: FileText, anyPerm: [PERM.REPORT_READ_OWN], group: 'health' },
  { href: '/alerts', label: 'Alerts', icon: Bell, anyPerm: [PERM.PATIENT_READ_OWN], group: 'health' },
  { href: '/admin', label: 'Admin', icon: ShieldHalf, anyPerm: [PERM.USERS_MANAGE, PERM.STAFF_MANAGE, PERM.AUDIT_READ], group: 'manage' },
];

const CRUMB: Record<string, string> = {
  '': 'Overview', patients: 'My record', reports: 'My reports', alerts: 'Alerts', admin: 'Admin',
  settings: 'Settings', privacy: 'Privacy policy',
};

function readCollapsed(): boolean {
  try { return window.localStorage.getItem('caresense.nav.collapsed') === '1'; } catch { return false; }
}
function writeCollapsed(value: boolean) {
  try { window.localStorage.setItem('caresense.nav.collapsed', value ? '1' : '0'); } catch { /* per-viewer nicety only */ }
}

function useOnline(): boolean {
  const [online, setOnline] = useState(() => (typeof navigator === 'undefined' ? true : navigator.onLine));
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down); };
  }, []);
  return online;
}

export function AppShell({ children }: { children: ReactNode }) {
  const [location, setLocation] = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const online = useOnline();
  const { user, logout, hasPermission, hasAnyPermission } = useAuth();
  const role = user ? primaryRole(user.roles) : undefined;
  const patientView = isPatientView(hasPermission);
  const canUpload = hasPermission(PERM.REPORT_UPLOAD_OWN);
  const activeHref = location.startsWith('/patients') ? '/patients' : location.startsWith('/reports') ? '/reports' : location;

  const notifications = useListNotifications({ page_size: 10 }, { query: { queryKey: getListNotificationsQueryKey({ page_size: 10 }), enabled: hasPermission(PERM.PATIENT_READ_OWN) } });
  const unread = ((notifications.data?.results || []) as Notification[]).filter((n) => n.status !== 'READ').length;

  const navItems = useMemo(() => NAV_ITEMS
    .filter((item) => !item.anyPerm || hasAnyPermission(...item.anyPerm))
    .map((item) => (patientView && item.href === '/patients'
      ? { ...item, label: 'My record' }
      : patientView && item.href === '/reports' ? { ...item, label: 'My reports' } : item)), [hasAnyPermission, patientView]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => { setMobileOpen(false); }, [location]);

  const toggleCollapsed = () => setCollapsed((value) => { writeCollapsed(!value); return !value; });
  const go = (href: string) => { setPaletteOpen(false); setLocation(href); };
  const upload = () => { setPaletteOpen(false); requestUpload(); setLocation('/reports'); };
  const segments = location.split('/').filter(Boolean);
  const crumb = segments[0] === 'patients' && !patientView ? 'Patients'
    : segments[0] === 'reports' && !patientView ? 'Reports'
    : CRUMB[segments[0] ?? ''] ?? 'Not found';
  const nested = segments.length > 1 && !(patientView && segments[0] === 'patients');

  const navList = (compact: boolean) => (
    <nav className="space-y-1" aria-label="Primary navigation">
      {navItems.map(({ href, label, icon: Icon }) => {
        const active = activeHref === href;
        return (
          <Link key={href} href={href} aria-current={active ? 'page' : undefined} title={compact ? label : undefined}
            className={`group relative flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-bold transition-colors ${compact ? 'justify-center' : ''} ${active ? 'bg-[hsl(var(--sidebar-primary)/.14)] text-[hsl(var(--sidebar-primary))]' : 'text-sidebar-foreground/65 hover:bg-sidebar-accent hover:text-sidebar-foreground'}`}
            data-testid={`link-nav-${label.toLowerCase().replace(/\s+/g, '-')}`}>
            <Icon size={18} strokeWidth={active ? 2.4 : 1.9} className="shrink-0" />
            {!compact && <span className="flex-1">{label}</span>}
            {href === '/alerts' && unread > 0 && <span className={`grid min-w-5 place-items-center rounded-full bg-[hsl(var(--accent))] px-1.5 text-[11px] font-bold leading-5 text-[hsl(var(--accent-foreground))] ${compact ? 'absolute right-1.5 top-1' : ''}`}>{unread}</span>}
          </Link>
        );
      })}
    </nav>
  );

  const sidebarBody = (compact: boolean) => (
    <>
      <div className={`flex items-center ${compact ? 'justify-center' : 'justify-between'} px-1`}>
        <Link href="/" className="flex items-center gap-2.5" data-testid="link-brand" aria-label="CareSense overview">
          <BrandMark size={34} />
          {!compact && <span className="leading-none"><span className="font-display block text-[21px] font-semibold text-sidebar-foreground">CareSense</span><span className="mono-label mt-1 block !text-[9.5px] text-sidebar-foreground/45">AI report reader</span></span>}
        </Link>
      </div>
      {canUpload && (
        <button type="button" onClick={upload} className="mt-7 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[hsl(var(--sidebar-primary))] text-[15px] font-bold text-[hsl(var(--sidebar-primary-foreground))] shadow-[0_8px_24px_-8px_hsl(var(--sidebar-primary)/.6)] transition-[filter,transform] hover:brightness-110 active:translate-y-px" title={compact ? 'Upload report' : undefined} data-testid="button-sidebar-upload">
          <Upload size={17} />{!compact && 'Upload report'}
        </button>
      )}
      <div className="mt-7">
        {!compact && <p className="mono-label mb-2.5 px-3 text-sidebar-foreground/40">Your health</p>}
        {navList(compact)}
      </div>
      <div className="mt-auto space-y-1">
        <Link href="/privacy" title={compact ? 'Privacy policy' : undefined} className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-bold ${compact ? 'justify-center' : ''} ${activeHref === '/privacy' ? 'bg-sidebar-accent text-sidebar-foreground' : 'text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground'}`} data-testid="link-nav-privacy"><ShieldCheck size={18} className="shrink-0" />{!compact && 'Privacy'}</Link>
        <Link href="/settings" title={compact ? 'Settings' : undefined} className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] font-bold ${compact ? 'justify-center' : ''} ${activeHref === '/settings' ? 'bg-sidebar-accent text-sidebar-foreground' : 'text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground'}`} data-testid="link-nav-settings"><Settings2 size={18} className="shrink-0" />{!compact && 'Settings'}</Link>
        <div className="!mt-4 border-t border-sidebar-border pt-4">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" className={`flex w-full items-center gap-3 rounded-xl p-2 text-left hover:bg-sidebar-accent ${compact ? 'justify-center' : ''}`} data-testid="button-user-menu">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-[hsl(var(--sidebar-primary)/.18)] text-[13px] font-bold text-[hsl(var(--sidebar-primary))]">{user ? initialsOf(user.full_name || user.email) : '—'}</span>
                {!compact && <span className="min-w-0 flex-1"><span className="block truncate text-sm font-bold text-sidebar-foreground">{user?.full_name || user?.email}</span><span className="block truncate text-xs text-sidebar-foreground/50">{role ? ROLE_LABEL[role] : ''}</span></span>}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-60">
              <DropdownMenuLabel className="font-normal"><span className="block text-sm font-bold">{user?.full_name}</span><span className="block truncate text-xs text-muted-foreground">{user?.email}</span></DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setLocation('/settings')}><Settings2 size={15} />Settings</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setLocation('/privacy')}><ShieldCheck size={15} />Privacy policy</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setHelpOpen(true)}><CircleHelp size={15} />Help</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => logout()} data-testid="button-logout"><LogOut size={15} />Sign out</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-[100dvh] bg-background text-foreground">
      {!online && <OfflineBanner />}

      {/* Desktop: a floating dock, inset from the window edge. */}
      <aside className={`fixed inset-y-3 left-3 z-40 hidden flex-col rounded-[20px] bg-sidebar px-3 py-5 text-sidebar-foreground shadow-xl transition-[width] duration-200 md:flex ${collapsed ? 'w-[76px]' : 'w-[256px]'}`}>
        {sidebarBody(collapsed)}
        <button type="button" onClick={toggleCollapsed} className="absolute -right-3 top-16 grid size-6 place-items-center rounded-full border border-border bg-card text-muted-foreground shadow-sm hover:text-foreground" aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'} data-testid="button-collapse-nav">
          {collapsed ? <ChevronsRight size={13} /> : <ChevronsLeft size={13} />}
        </button>
      </aside>

      {/* Mobile: a slide-in drawer. */}
      {mobileOpen && <button aria-label="Close menu overlay" className="fixed inset-0 z-40 bg-[hsl(var(--foreground)/.4)] md:hidden" onClick={() => setMobileOpen(false)} data-testid="button-navigation-overlay" />}
      <aside className={`fixed inset-y-0 left-0 z-50 flex w-[280px] flex-col bg-sidebar px-4 py-5 text-sidebar-foreground transition-transform duration-200 md:hidden ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`} aria-hidden={!mobileOpen}>
        <button className="absolute right-3 top-4 rounded-lg p-2 text-sidebar-foreground/60 hover:bg-sidebar-accent" onClick={() => setMobileOpen(false)} aria-label="Close navigation" data-testid="button-close-navigation"><X size={18} /></button>
        {mobileOpen && sidebarBody(false)}
      </aside>

      <div className={`transition-[padding] duration-200 ${collapsed ? 'md:pl-[100px]' : 'md:pl-[280px]'}`}>
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 border-b border-border/70 bg-background/85 px-4 backdrop-blur-md sm:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button className="rounded-lg p-2 hover:bg-secondary md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation" data-testid="button-open-navigation"><Menu size={20} /></button>
            <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-sm">
              <Link href="/" className="hidden text-muted-foreground hover:text-foreground sm:inline">CareSense</Link>
              <span className="hidden text-muted-foreground/50 sm:inline">/</span>
              {nested ? <><Link href={`/${segments[0]}`} className="truncate text-muted-foreground hover:text-foreground">{crumb}</Link><span className="text-muted-foreground/50">/</span><span className="truncate font-bold">Details</span></> : <span className="truncate font-bold">{crumb}</span>}
            </nav>
          </div>
          <div className="flex items-center gap-1.5">
            <button type="button" onClick={() => setPaletteOpen(true)} className="hidden h-10 w-64 items-center gap-2 rounded-xl border border-input bg-card px-3 text-sm text-muted-foreground transition-colors hover:border-ring lg:flex" data-testid="button-open-search">
              <Search size={16} /><span className="flex-1 text-left">Search or jump to…</span><kbd className="mono-label rounded border border-border bg-secondary px-1.5 py-0.5 !text-[10px]">Ctrl K</kbd>
            </button>
            <button type="button" onClick={() => setPaletteOpen(true)} className="grid size-10 place-items-center rounded-xl text-muted-foreground hover:bg-secondary lg:hidden" aria-label="Search"><Search size={18} /></button>
            <button onClick={() => setLocation('/alerts')} className="relative grid size-10 place-items-center rounded-xl text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label={unread ? `Alerts and messages, ${unread} unread` : 'Alerts and messages'} data-testid="button-header-alerts">
              <Bell size={18} />{unread > 0 && <span className="absolute right-2 top-2 size-2 rounded-full bg-[hsl(var(--accent))] ring-2 ring-background" />}
            </button>
            <button onClick={() => setHelpOpen(true)} className="grid size-10 place-items-center rounded-xl text-muted-foreground hover:bg-secondary" aria-label="Help" data-testid="button-help"><CircleHelp size={18} /></button>
          </div>
        </header>

        <main className="mx-auto max-w-[1360px] px-4 pb-28 pt-8 sm:px-8 md:pb-12 lg:pt-10">{children}</main>

        <footer className="mx-auto hidden max-w-[1360px] items-center justify-between gap-4 border-t border-border px-8 py-6 text-[13px] text-muted-foreground md:flex">
          <span>CareSense explains reports. It does not diagnose. Always show your results to a doctor.</span>
          <span className="flex items-center gap-4"><Link href="/privacy" className="font-bold hover:text-foreground">Privacy policy</Link><button type="button" onClick={() => setHelpOpen(true)} className="font-bold hover:text-foreground">Help</button></span>
        </footer>
      </div>

      {/* Mobile tab bar with a raised upload action in the middle. */}
      <nav className="fixed inset-x-3 bottom-3 z-30 grid h-16 grid-cols-5 items-center rounded-2xl border border-border bg-card/95 px-1 shadow-lg backdrop-blur md:hidden" aria-label="Quick navigation">
        {[navItems[0], navItems[1]].filter(Boolean).map(({ href, label, icon: Icon }) => <MobileTab key={href} href={href} label={label} Icon={Icon} active={activeHref === href} />)}
        {canUpload ? <button type="button" onClick={upload} className="mx-auto -mt-7 grid size-14 place-items-center rounded-2xl bg-primary text-primary-foreground shadow-[0_10px_24px_-8px_hsl(var(--primary)/.7)] ring-4 ring-background" aria-label="Upload report" data-testid="button-mobile-upload"><Upload size={22} /></button> : <span />}
        {[navItems[2], navItems[3]].filter(Boolean).map(({ href, label, icon: Icon }) => <MobileTab key={href} href={href} label={label} Icon={Icon} active={activeHref === href} />)}
      </nav>

      <CommandDialog open={paletteOpen} onOpenChange={setPaletteOpen}>
        <CommandInput placeholder="Search pages and actions…" data-testid="input-command" />
        <CommandList>
          <CommandEmpty>Nothing found.</CommandEmpty>
          <CommandGroup heading="Go to">
            {navItems.map(({ href, label, icon: Icon }) => <CommandItem key={href} value={label} onSelect={() => go(href)}><Icon />{label}</CommandItem>)}
            <CommandItem value="Settings" onSelect={() => go('/settings')}><Settings2 />Settings</CommandItem>
            <CommandItem value="Privacy policy" onSelect={() => go('/privacy')}><ShieldCheck />Privacy policy</CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Actions">
            {canUpload && <CommandItem value="Upload a report" onSelect={upload}><Upload />Upload a report<CommandShortcut>New</CommandShortcut></CommandItem>}
            <CommandItem value="Help" onSelect={() => { setPaletteOpen(false); setHelpOpen(true); }}><CircleHelp />Help</CommandItem>
            <CommandItem value="Sign out" onSelect={() => { setPaletteOpen(false); void logout(); }}><LogOut />Sign out</CommandItem>
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      {helpOpen && <Modal title="Help" description="What CareSense can and cannot do for you." onClose={() => setHelpOpen(false)}>
        <div className="space-y-4 text-[15px] leading-relaxed text-muted-foreground">
          <p><strong className="text-foreground">What it does.</strong> Upload a lab report and our AI reads each value, compares it with the normal range printed on the report, and explains what it found in simple words.</p>
          <p><strong className="text-foreground">What it does not do.</strong> It does not diagnose and it does not replace a doctor. When it is not sure, it holds back and tells you why.</p>
          <p className="rounded-xl border border-[hsl(var(--destructive)/.3)] bg-[hsl(var(--destructive)/.05)] p-3.5 text-foreground"><strong>Feeling unwell right now?</strong> Do not wait for anything on this screen. Contact a doctor or call 112.</p>
          <p className="text-sm">Tip: press <kbd className="mono-label rounded border border-border bg-secondary px-1.5 py-0.5 !text-[10px]">Ctrl K</kbd> anywhere to search.</p>
        </div>
        <div className="mt-6 flex justify-end">
          <button type="button" onClick={() => setHelpOpen(false)} className="inline-flex h-11 items-center rounded-lg bg-primary px-5 text-sm font-bold text-primary-foreground" data-testid="button-help-close">Close</button>
        </div>
      </Modal>}
    </div>
  );
}

function MobileTab({ href, label, Icon, active }: { href: string; label: string; Icon: typeof LayoutDashboard; active: boolean }) {
  return (
    <Link href={href} className={`grid h-full place-items-center content-center gap-0.5 text-[11px] font-bold ${active ? 'text-[hsl(var(--brand))]' : 'text-muted-foreground'}`} aria-current={active ? 'page' : undefined} data-testid={`link-mobile-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <Icon size={19} strokeWidth={active ? 2.4 : 1.9} /><span className="truncate">{label}</span>
    </Link>
  );
}
