/**
 * Providers, the sign-in gate and the router. Pages live in src/pages and the
 * signed-in frame in components/app-shell.
 */
import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { Route, Switch, Router as WouterRouter, useLocation } from 'wouter';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/toaster';
import { ErrorBoundary } from '@/components/error-boundary';
import { AppShell } from '@/components/app-shell';
import { BrandMark, NotFoundPage, UnreachablePage } from '@/components/error-page';
import { AuthProvider, useAuth } from '@/lib/auth';
import { queryClient } from '@/lib/query-client';
import Login from '@/pages/login';
import SignUp from '@/pages/signup';
import AdminConsole from '@/pages/admin';
import Dashboard from '@/pages/dashboard';
import Reports from '@/pages/reports';
import ReportDetailPage from '@/pages/report-detail';
import Alerts from '@/pages/alerts';
import Settings from '@/pages/settings';
import PrivacyPolicy from '@/pages/privacy';
import { PatientProfilePage, Patients } from '@/pages/record';


function AuthenticatedRouter() {
  const [location] = useLocation();
  return (
    <ErrorBoundary resetKey={location}>
      <AppShell>
        <Switch>
          <Route path="/" component={Dashboard} />
          <Route path="/patients" component={Patients} />
          <Route path="/patients/:patientId" component={PatientProfilePage} />
          <Route path="/reports" component={Reports} />
          <Route path="/reports/:reportId" component={ReportDetailPage} />
          <Route path="/admin" component={AdminConsole} />
          <Route path="/alerts" component={Alerts} />
          <Route path="/settings" component={Settings} />
          <Route path="/privacy">{() => <PrivacyPolicy />}</Route>
          <Route>{() => <NotFoundPage />}</Route>
        </Switch>
      </AppShell>
    </ErrorBoundary>
  );
}

function FullPageLoading() {
  return (
    <div className="grid min-h-[100dvh] place-items-center bg-background">
      <div className="flex flex-col items-center gap-4 text-muted-foreground">
        <span className="animate-pulse"><BrandMark size={44} /></span>
        <p className="text-sm">Opening CareSense…</p>
      </div>
    </div>
  );
}

function Gate() {
  const { user, isLoading, unreachable, retryConnection } = useAuth();
  const [location] = useLocation();
  const [showSignUp, setShowSignUp] = useState(false);
  // The privacy policy is public: someone deciding whether to sign up must be
  // able to read it first.
  if (location === '/privacy' && !user && !isLoading) return <PrivacyPolicy standalone />;
  if (isLoading) return <FullPageLoading />;
  if (unreachable && !user) return <UnreachablePage onRetry={retryConnection} />;
  if (!user) {
    return showSignUp
      ? <SignUp onShowLogin={() => setShowSignUp(false)} />
      : <Login onShowSignUp={() => setShowSignUp(true)} />;
  }
  return <AuthenticatedRouter />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TooltipProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
            <Gate />
          </WouterRouter>
          <Toaster />
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
