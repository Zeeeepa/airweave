/**
 * Auth Provider Compatibility Matrix
 * 
 * This defines which sources are compatible with which auth providers.
 * Used to show/hide auth provider options in the UI.
 */

export const AUTH_PROVIDER_COMPATIBILITY = {
    composio: {
        // Sources that Composio supports
        github: true,
        confluence: true,
        jira: true,
        bitbucket: true,
        monday: true,
        ctti: true,
        slack: true,
        gmail: true,
        google_drive: true,
        google_calendar: true,
        asana: true,
        clickup: true,
        dropbox: true,
        elasticsearch: true,
        notion: true,
        todoist: true,
        trello: true,
        zendesk: true,
        // Database sources - Composio doesn't support direct DB connections
        postgresql: false,
        mysql: false,
        sqlite: false,
        oracle: false,
        sql_server: false,
        // Other sources
        stripe: true,
        intercom: true,
        linear: true,
        hubspot: true,
        onedrive: true,
        outlook_mail: true,
        outlook_calendar: true,
    },
    pipedream: {
        // Sources that Pipedream supports
        github: true,
        confluence: true,
        jira: true,
        bitbucket: true,
        monday: true,
        postgresql: true, // Pipedream supports DB connections
        mysql: true,
        sqlite: true,
        oracle: true,
        sql_server: true,
        ctti: true,
        slack: true,
        gmail: true,
        google_drive: true,
        google_calendar: true,
        asana: true,
        clickup: true,
        dropbox: true,
        elasticsearch: true,
        notion: true,
        todoist: true,
        trello: true,
        zendesk: true,
        // Other sources
        stripe: true,
        intercom: true,
        linear: true,
        hubspot: true,
        onedrive: true,
        outlook_mail: true,
        outlook_calendar: true,
    }
} as const;

export type AuthProviderShortName = keyof typeof AUTH_PROVIDER_COMPATIBILITY;
export type SourceShortName = keyof typeof AUTH_PROVIDER_COMPATIBILITY.composio;

/**
 * Check if a source is compatible with a specific auth provider
 */
export function isSourceCompatibleWithAuthProvider(
    sourceShortName: string,
    authProviderShortName: AuthProviderShortName
): boolean {
    const providerCompatibility = AUTH_PROVIDER_COMPATIBILITY[authProviderShortName];
    return providerCompatibility[sourceShortName as SourceShortName] === true;
}

/**
 * Get all compatible auth providers for a given source
 */
export function getCompatibleAuthProviders(sourceShortName: string): AuthProviderShortName[] {
    const compatibleProviders: AuthProviderShortName[] = [];

    for (const providerShortName of Object.keys(AUTH_PROVIDER_COMPATIBILITY) as AuthProviderShortName[]) {
        if (isSourceCompatibleWithAuthProvider(sourceShortName, providerShortName)) {
            compatibleProviders.push(providerShortName);
        }
    }

    return compatibleProviders;
}

/**
 * Check if a source has any compatible auth providers
 */
export function hasCompatibleAuthProviders(sourceShortName: string): boolean {
    return getCompatibleAuthProviders(sourceShortName).length > 0;
}
