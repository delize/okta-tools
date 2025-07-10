(async () => {
    // NOTE !!!!!!!!!!!!!!!!!!
    // This is specifically for Office 365 Microsoft App, change the URL below before using for a different App!
    // NOTE
    const baseUrl = "https://$SUBDOMAIN-admin.okta-emea.com/api/internal/instance/$APPID";
    const pushGroupUrl = `${baseUrl}/grouppush`;

    // Replace with your actual Okta API Key
    const apiKey = "$APIKEY";

    async function fetchPushGroups(url) {
        let allGroups = [];
        let nextUrl = url;

        while (nextUrl) {
            console.log(`Fetching: ${nextUrl}`);
            let response = await fetch(nextUrl, {
                method: "GET",
                headers: {
                    "Authorization": `SSWS ${apiKey}`,
                    "Accept": "application/json"
                }
            });

            if (!response.ok) {
                console.error(`Failed to fetch groups: ${response.status} - ${response.statusText}`);
                return [];
            }

            let data = await response.json();
            allGroups.push(...data.mappings);

            nextUrl = data.nextMappingsPageUrl || null;
        }

        return allGroups;
    }

    async function delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async function activatePushGroup(mappingId, attempt = 1) {
        const activateUrl = `${pushGroupUrl}/${mappingId}`;
        console.log(`Activating group: ${mappingId} (Attempt ${attempt})`);

        let headers = {
            "Content-Type": "application/json",
            "Authorization": `SSWS ${apiKey}`,
            "Accept": "application/json"
        };

        try {
            let response = await fetch(activateUrl, {
                method: "PUT",
                headers: headers,
                body: JSON.stringify({ status: "ACTIVE" })
            });

            if (response.status === 429) {
                let retryAfter = response.headers.get("Retry-After") || (attempt * 2000);
                retryAfter = Math.min(retryAfter, 30000);
                console.warn(`Rate limited! Retrying group ${mappingId} after ${retryAfter}ms...`);
                await delay(retryAfter);
                return activatePushGroup(mappingId, attempt + 1);
            }

            if (response.status === 403) {
                console.error(`403 Forbidden: Ensure your API key has the correct permissions.`);
                return;
            }

            if (!response.ok) {
                console.error(`Failed to activate group ${mappingId}: ${response.status} - ${response.statusText}`);
                return;
            }

            console.log(`Successfully activated group ${mappingId}`);

        } catch (error) {
            console.error(`Error activating group ${mappingId}: ${error.message}`);
        }
    }

    // Fetch all groups
    let pushGroups = await fetchPushGroups(pushGroupUrl);
    console.log(`Found ${pushGroups.length} push groups`);

    // Activate only INACTIVE groups
    let inactiveGroups = pushGroups.filter(group => group.status === "INACTIVE");

    console.log(`Activating ${inactiveGroups.length} inactive push groups...`);
    for (let group of inactiveGroups) {
        await activatePushGroup(group.mappingId);
        await delay(1000);
    }

    console.log("All push groups activated successfully.");
})();