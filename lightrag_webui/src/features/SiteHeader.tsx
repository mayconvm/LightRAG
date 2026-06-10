import { useCallback, useEffect, useState } from 'react'
import Button from '@/components/ui/Button'
import { SiteInfo, webuiPrefix } from '@/lib/constants'
import AppSettings from '@/components/AppSettings'
import { TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/state'
import { cn } from '@/lib/utils'
import { useTranslation } from 'react-i18next'
import { navigationService } from '@/services/navigation'
import { ZapIcon, LogOutIcon, LayersIcon } from 'lucide-react'
import GithubIcon from '@/components/icons/GithubIcon'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/Select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/Tooltip'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/Dialog'
import Input from '@/components/ui/Input'
import * as api from '@/api/lightrag'

interface NavigationTabProps {
  value: string
  currentTab: string
  children: React.ReactNode
}

function NavigationTab({ value, currentTab, children }: NavigationTabProps) {
  return (
    <TabsTrigger
      value={value}
      className={cn(
        'cursor-pointer px-2 py-1 transition-all',
        currentTab === value ? '!bg-emerald-400 !text-zinc-50' : 'hover:bg-background/60'
      )}
    >
      {children}
    </TabsTrigger>
  )
}

function TabsNavigation() {
  const currentTab = useSettingsStore.use.currentTab()
  const { t } = useTranslation()

  return (
    <div className="flex h-8 self-center">
      <TabsList className="h-full gap-2">
        <NavigationTab value="documents" currentTab={currentTab}>
          {t('header.documents')}
        </NavigationTab>
        <NavigationTab value="knowledge-graph" currentTab={currentTab}>
          {t('header.knowledgeGraph')}
        </NavigationTab>
        <NavigationTab value="retrieval" currentTab={currentTab}>
          {t('header.retrieval')}
        </NavigationTab>
        <NavigationTab value="api" currentTab={currentTab}>
          {t('header.api')}
        </NavigationTab>
      </TabsList>
    </div>
  )
}

export default function SiteHeader() {
  const { t } = useTranslation()
  const { isGuestMode, coreVersion, apiVersion, username, webuiTitle, webuiDescription } = useAuthStore()

  const activeWorkspace = useSettingsStore.use.activeWorkspace()
  const setActiveWorkspace = useSettingsStore.use.setActiveWorkspace()
  const availableWorkspaces = useSettingsStore.use.availableWorkspaces()
  const setAvailableWorkspaces = useSettingsStore.use.setAvailableWorkspaces()

  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [newWorkspaceName, setNewWorkspaceName] = useState('')

  const versionDisplay = (coreVersion && apiVersion)
    ? `${coreVersion}/${apiVersion}`
    : null;

  const hasWarning = apiVersion?.endsWith('⚠️');
  const versionTooltip = hasWarning
    ? t('header.frontendNeedsRebuild')
    : versionDisplay ? `v${versionDisplay}` : '';

  const handleLogout = () => {
    navigationService.navigateToLogin();
  }

  const refreshWorkspaces = useCallback(async () => {
    try {
      const resp = await api.listWorkspaces()
      setAvailableWorkspaces(resp.workspaces || [])
    } catch { /* server may not support workspaces yet */ }
  }, [setAvailableWorkspaces])

  useEffect(() => {
    refreshWorkspaces()
  }, [refreshWorkspaces])

  const handleWorkspaceChange = useCallback((value: string) => {
    setActiveWorkspace(value === '_default' ? '' : value)
  }, [setActiveWorkspace])

  const handleCreateWorkspace = useCallback(async () => {
    const name = newWorkspaceName.trim()
    if (!name) return
    try {
      await api.createWorkspace(name)
      setActiveWorkspace(name)
      setNewWorkspaceName('')
      setCreateDialogOpen(false)
      await refreshWorkspaces()
    } catch (e) {
      console.error('Failed to create workspace', e)
    }
  }, [newWorkspaceName, setActiveWorkspace, refreshWorkspaces])

  const handleDeleteWorkspace = useCallback(async (ws: string) => {
    if (!ws) return
    try {
      await api.deleteWorkspace(ws)
      if (activeWorkspace === ws) {
        setActiveWorkspace('')
      }
      await refreshWorkspaces()
    } catch (e) {
      console.error('Failed to delete workspace', e)
    }
  }, [activeWorkspace, setActiveWorkspace, refreshWorkspaces])

  const displayWorkspace = activeWorkspace || '_default'

  return (
    <header className="border-border/40 bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-50 flex h-10 w-full border-b px-4 backdrop-blur">
      <div className="min-w-[200px] w-auto flex items-center">
        <a href={webuiPrefix} className="flex items-center gap-2">
          <ZapIcon className="size-4 text-emerald-400" aria-hidden="true" />
          <span className="font-bold md:inline-block">{SiteInfo.name}</span>
        </a>
        {webuiTitle && (
          <div className="flex items-center">
            <span className="mx-1 text-xs text-gray-500 dark:text-gray-400">|</span>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="font-medium text-sm cursor-default">
                    {webuiTitle}
                  </span>
                </TooltipTrigger>
                {webuiDescription && (
                  <TooltipContent side="bottom">
                    {webuiDescription}
                  </TooltipContent>
                )}
              </Tooltip>
            </TooltipProvider>
          </div>
        )}
      </div>

      <div className="flex h-10 flex-1 items-center justify-center">
        <TabsNavigation />
        {isGuestMode && (
          <div className="ml-2 self-center px-2 py-1 text-xs bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 rounded-md">
            {t('login.guestMode', 'Guest Mode')}
          </div>
        )}
      </div>

      <nav className="w-[200px] flex items-center justify-end">
        <div className="flex items-center gap-1">
          {/* Workspace selector */}
          <div className="flex items-center gap-1">
            <LayersIcon className="size-3 text-muted-foreground" />
            <Select value={displayWorkspace} onValueChange={handleWorkspaceChange}>
              <SelectTrigger className="h-7 w-[110px] border-0 bg-transparent px-1 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="_default">
                  {t('workspace.default', 'Default')}
                </SelectItem>
                {availableWorkspaces.map((ws) => (
                  <SelectItem key={ws} value={ws}>
                    <span className="flex items-center gap-1">
                      {ws}
                      <button
                        className="ml-1 text-muted-foreground hover:text-destructive"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDeleteWorkspace(ws)
                        }}
                        title={t('workspace.delete', 'Delete')}
                      >
                        ×
                      </button>
                    </span>
                  </SelectItem>
                ))}
                <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
                  <DialogTrigger asChild>
                    <button
                      className="relative flex w-full cursor-default items-center rounded-sm py-1.5 pl-8 pr-2 text-xs hover:bg-accent hover:text-accent-foreground outline-none select-none"
                    >
                      + {t('workspace.create', 'New Workspace')}
                    </button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>{t('workspace.createTitle', 'Create Workspace')}</DialogTitle>
                    </DialogHeader>
                    <div className="flex flex-col gap-3">
                      <Input
                        placeholder={t('workspace.namePlaceholder', 'Workspace name')}
                        value={newWorkspaceName}
                        onChange={(e) => setNewWorkspaceName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleCreateWorkspace()}
                      />
                      <Button onClick={handleCreateWorkspace} className="self-end">
                        {t('workspace.create', 'Create')}
                      </Button>
                    </div>
                  </DialogContent>
                </Dialog>
              </SelectContent>
            </Select>
          </div>

          {versionDisplay && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="text-xs text-gray-500 dark:text-gray-400 cursor-default">
                    v{versionDisplay}
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  {versionTooltip}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
          <Button variant="ghost" size="icon" side="bottom" tooltip={t('header.projectRepository')}>
            <a href={SiteInfo.github} target="_blank" rel="noopener noreferrer">
              <GithubIcon className="size-4" />
            </a>
          </Button>
          <AppSettings />
          {!isGuestMode && (
            <Button
              variant="ghost"
              size="icon"
              side="bottom"
              tooltip={`${t('header.logout')} (${username})`}
              onClick={handleLogout}
            >
              <LogOutIcon className="size-4" aria-hidden="true" />
            </Button>
          )}
        </div>
      </nav>
    </header>
  )
}
