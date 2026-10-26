import type { ReactNode } from 'react';
import { IconBuilding, IconCart, IconChart, IconCoin, IconDrop, IconGlobe, IconGrain, IconNews, IconTrend, IconUsers } from './Icons';

/** Нейтральная иконка темы события — у новостей из API нет изображений, чужие фото не подставляем. */
export function eventIcon(type: string | undefined, size = 30): ReactNode {
  switch (type) {
    case 'key_rate':
    case 'credit_market':
      return <IconChart size={size} />;
    case 'inflation':
    case 'gdp_macro':
      return <IconTrend size={size} />;
    case 'fx':
    case 'budget_tax':
      return <IconCoin size={size} />;
    case 'fuel_energy':
    case 'metals':
    case 'gold':
      return <IconDrop size={size} />;
    case 'agri':
      return <IconGrain size={size} />;
    case 'consumer_demand':
      return <IconCart size={size} />;
    case 'labor_market':
      return <IconUsers size={size} />;
    case 'trade_sanctions':
      return <IconGlobe size={size} />;
    case 'real_estate':
      return <IconBuilding size={size} />;
    default:
      return <IconNews size={size} />;
  }
}
