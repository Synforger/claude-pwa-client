// The tier of a tab as the drawer shows it, next to the account: the last name of the tier
// (`projects/alpha` -> `alpha`, `normal` -> `normal`). A tab whose tier is not known shows nothing.

export function tierLabel(tier) {
  if (typeof tier !== 'string' || tier === '') return null
  const last = tier.split('/').filter(Boolean).pop()
  return last || null
}
