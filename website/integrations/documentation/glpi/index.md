---
title: Integrate with Gestionnaire Libre de Parc Informatique
sidebar_label: Gestionnaire Libre de Parc Informatique
support_level: community
---

## What is GLPI

> GLPI (Gestionnaire Libre de Parc Informatique) is an open-source IT asset management and service desk software. It helps organizations manage hardware, software, tickets, users, and IT services in a centralized platform.
>
> -- https://www.glpi-project.org

:::info
This is based on authentik 2024.8 and GLPI v11.x with the samlsso plugin v1.x. Instructions may differ between versions.
:::

## Preparation

The following placeholders are used in this guide:

- `glpi.company` is the FQDN of the GLPI installation.
- `authentik.company` is the FQDN of the authentik installation.

:::info
This documentation lists only the settings that you need to change from their default values. Be aware that any changes other than those explicitly mentioned in this guide could cause issues accessing your application.
:::

By default, GLPI only offers OAuth authentication, which is only available to GLPI Network subscribers. This guide uses a community plugin named `samlsso` by DonutsNL, which provides SAML authentication support for GLPI v11+.

> https://github.com/DonutsNL/samlsso

### Install the samlsso plugin

Before configuring the SAML integration, you must install the `samlsso` plugin in GLPI.

1. Download the latest release of `samlsso.zip` from the [GitHub releases page](https://github.com/DonutsNL/samlsso/releases).
2. Unpack the zip file into the `glpiroot/data/marketplace` directory on your GLPI server.
3. Log in to GLPI as an administrator.
4. Navigate to **Setup** > **Plugins**.
5. Find the **samlSSO** plugin in the list and click **Install**.
6. After installation, click **Activate** to enable the plugin.

## GLPI pre-configuration

Before setting up authentik, you need to create a SAML instance in GLPI to obtain the Service Provider metadata.

### Create a new SAML instance

1. In GLPI, navigate to **Setup** > **samlSSO**.
2. Click **Add a new instance** (or the **+** button).
3. Configure the instance with the following settings:

    **General tab:**
    - **Friendly name**: `authentik`
    - **Login icon**: Select an icon from [FontAwesome](https://fontawesome.com/) (e.g., `fa-sign-in` or `fa-shield`)
    - **Is active**: Check this box.

    **Transit tab:**
    - **Validate XML**: Check this box.
    **Security tab:**
    - **Strict**: Check this box.
    - **Jit user creation**: Check this box.

4. Click **Save** to create the instance.

### Note the Service Provider information

After saving, navigate to the **Service Provider** tab of your newly created instance and take note of the **Entity ID** and **AcsUrl**.

## authentik configuration

To support the integration of GLPI with authentik, you need to create an application/provider pair in authentik.

### Create an application and provider in authentik

1. Log in to authentik as an administrator and open the authentik Admin interface.
2. Navigate to **Applications** > **Applications** and click **Create with Provider** to create an application and provider pair. (Alternatively you can first create a provider separately, then create the application and connect it with the provider.)

- **Application**: provide a descriptive name, an optional group for the type of application, the policy engine mode, and optional UI settings.
- **Choose a Provider type**: select **SAML Provider** as the provider type.
- **Configure the Provider**: provide a name (or accept the auto-provided name), the authorization flow to use for this provider, and the following required configurations.
    - Enter the **ACS URL** from the GLPI samlSSO Service Provider tab.
    - Enter the **Issuer** from the Entity ID in the GLPI samlSSO Service Provider tab.
    - Set the **Service Provider Binding** to **Post**.
    - Under **Advanced protocol settings**, select any available signing key and enable **Sign assertions**.
    - Under **Advanced protocol settings**, set **NameID Property Mapping** to `authentik default SAML Mapping: Email`.
- **Configure Bindings** _(optional)_: you can create a [binding](/docs/add-secure-apps/flows-stages/bindings/) (policy, group, or user) to manage the listing and access to applications on a user's **My applications** page.

3. Click **Submit** to save the new application and provider.

### Note the Identity Provider information

After creating the provider, navigate to **Applications** > **Providers** and click on your newly created GLPI provider. Take note of the following values:

- **SSO URL (Redirect)**
- **SLO URL (Redirect)**

Under **SAML Metadata**, click **Download signing certificate** to download the X.509 certificate file.

## GLPI Identity Provider configuration

Now that you have created the authentik provider, you need to configure GLPI to use authentik as the Identity Provider.

### Configure the Identity Provider in GLPI

1. Return to GLPI and navigate to **Setup** > **samlSSO**.
2. Click on your created samlSSO instance (e.g., `authentik`).
3. Navigate to the **Identity Provider** tab.
4. Configure the following settings:

    - **Entity ID**: Enter the Entity ID from your GLPI Service Provider configuration, **removing any trailing slash**.
        :::warning
        The Entity ID must not have a trailing slash, or authentication will fail.
        :::
    - **SSO URL**: Enter the **SSO URL (Redirect)** from the authentik provider.
    - **SLO URL**: Enter the **SLO URL (Redirect)** from the authentik provider.
    - **X509 certificate**: Open the certificate file you downloaded from authentik in a text editor and copy the entire contents (including the `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----` lines). Paste this into the X509 certificate field.

5. Click **Save** to apply the changes.

:::info
**Note**: GLPI using `redirect` binding URLs while the authentik provider is configured with `post` binding is not a mistake. The samlsso plugin handles both bindings appropriately.
:::

## Just-In-Time (JIT) user provisioning

The samlsso plugin supports automatic user creation and profile assignment through JIT provisioning rules. These rules allow you to automatically assign GLPI profiles and entities to users based on SAML assertion attributes.

:::info
JIT rules in the samlsso plugin currently only support checking user attributes from the SAML assertion. They do not support checking authentik group memberships directly. However, you can create custom SAML property mappings in authentik to include group information as user attributes.
:::

### Configure JIT import rules

1. In GLPI, navigate to **Setup** > **samlSSO** > **JIT import rules**.
2. Click **Add** to create a new rule.
3. Configure the rule:

    **Criteria section:**
    - Define conditions that must be met for the rule to apply. Criteria are evaluated against the authenticated user's SAML attributes.
    - Example criteria:
        - **Attribute**: `email`
        - **Condition**: `contains`
        - **Value**: `@company.com`

    **Actions section:**
    - Define what happens when the criteria match. Actions configure the user's GLPI profile and access.
    - Common actions include:
        - **Profile assignment**: Assign a specific GLPI profile (e.g., `Admin`, `Technician`, `Self-Service`)
        - **Entity assignment**: Assign the user to specific GLPI entities
        - **Recursive rights**: Add `recursive=yes` to give users access to all sub-entities

    :::info
    Setting `recursive=yes` as an action allows matched users to access all entities in the GLPI hierarchy, not just the directly assigned entity. This is useful for administrators and technicians who need broad access.
    :::

4. Click **Save** to create the rule.

### Example JIT rule

Here's an example of a JIT rule that assigns all users with an email domain of `@company.com` to the `Technician` profile with recursive entity access:

**Criteria:**
- Attribute: `email`
- Condition: `contains`
- Value: `@company.com`

**Actions:**
- Profile: `Technician`
- Entity: `Root entity`
- Recursive: `yes`

### Advanced JIT provisioning with custom SAML mappings

If you need to assign profiles based on authentik groups, you can create a custom SAML property mapping in authentik:

1. In authentik, navigate to **Customization** > **Property Mappings**.
2. Click **Create** and select **SAML Property Mapping**.
3. Configure the mapping:
    - **Name**: `GLPI Group Mapping`
    - **SAML Attribute Name**: `groups`
    - **Expression**:
      ```python
      return [group.name for group in request.user.ak_groups.all()]
      ```
4. Add this mapping to your GLPI SAML provider under **Property mappings**.

Then, in GLPI, you can create JIT rules that check the `groups` attribute for specific group names.

## Configuration verification

To confirm that authentik is properly configured with GLPI, log out and click the new authentik login button on the GLPI login page. You will be redirected to authentik and once authenticated, you will be signed in to GLPI.

### Troubleshooting

If you encounter issues during authentication:

- **Check the SAML response**: In authentik, navigate to **Events** > **Logs** to view SAML requests and responses. Look for errors or missing attributes.
- **Verify certificate**: Ensure the X.509 certificate in GLPI matches the signing certificate from authentik exactly (including line breaks).
- **Check Entity ID**: Ensure the Entity ID in GLPI's Identity Provider configuration does not have a trailing slash.
- **Review JIT rules**: If users are created but not assigned profiles, review your JIT import rules to ensure the criteria match the user attributes.
- **Enable GLPI debugging**: In GLPI, you can enable plugin debugging to see detailed SAML processing logs. Check with the samlsso plugin documentation for specific debug options.

## Additional resources

- [GLPI official documentation](https://glpi-project.org/documentation/)
- [samlsso plugin GitHub repository](https://github.com/DonutsNL/samlsso)
- [authentik SAML provider documentation](/docs/add-secure-apps/providers/saml/)
