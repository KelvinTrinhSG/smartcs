# n8n image for Render: workflows are baked in and re-imported on every start, so git is the source of
# truth (edits made in the hosted editor are overwritten on the next deploy). Credentials come from env.
FROM n8nio/n8n:2.44.4
COPY --chown=node:node workflows /workflows
COPY --chown=node:node render-start.sh /render-start.sh
ENTRYPOINT ["tini", "--", "/bin/sh", "/render-start.sh"]
