# policies/mcp/gateway.rego — Phase 0 MCP Gateway blast-radius policy.
#
# Enforces tool filtering and call authorization based on agent blast radius.
# Unknown/unannotated tools default to "infrastructure" (highest risk) so they
# are denied by default to lower-privilege agents.
#
# Design: §5.3–§5.4, §11.4, §17.2 OQ-20
package mcp.gateway

import rego.v1

# Blast radius ordering: read_only < workspace < infrastructure
# Lower rank = lower privilege = less blast radius.
radius_rank := {"read_only": 0, "workspace": 1, "infrastructure": 2}

# Determine the blast radius a tool requires.
# If the tool has an annotations.blast_radius field, use it.
# Otherwise default to "infrastructure" (highest risk) — unknown tools
# must NOT gain a lower blast radius.
tool_radius(tool) := tool.annotations.blast_radius if {
	tool.annotations.blast_radius
} else := "infrastructure"

# A tool is allowed for an agent if the tool's required radius rank
# is at or below the agent's granted radius rank.
allow_tool(tool, agent_radius) if {
	radius_rank[tool_radius(tool)] <= radius_rank[agent_radius]
}

# Filter rule: returns the subset of tools the agent is allowed to see.
filter := [t |
	some t in input.tools
	allow_tool(t, input.agent_blast_radius)
]

# Allow rule: for tools/call authorization — is the specific named tool
# allowed for this agent's blast radius?
allow if {
	some t in input.tools
	t.name == input.tool
	allow_tool(t, input.agent_blast_radius)
}
