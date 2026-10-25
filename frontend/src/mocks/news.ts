// МОКОВЫЕ ДАННЫЕ. Используются только при VITE_USE_MOCKS=1.
// Новости — учебные фикстуры (источник помечен «[мок]», ссылки ведут на example.com).
// Фрагменты аналитики банка — дословно из data/bank_corpus/corpus.json.
import type { Event, News } from '../api/types';

export interface MockNews extends News {
  event: Event;
  /** веса каналов влияния (как в ai/app/events.py) */
  channels: Record<string, number>;
  importance: number;
  business: boolean;
  bankChunks: string[];
}

const ts = (d: string) => `${d}+03:00`;
const FETCHED = '2026-10-24T15:00:00Z';

function mk(
  id: string,
  p: Omit<MockNews, 'id' | 'fetched_at' | 'origin' | 'content'> & { content?: string },
): MockNews {
  return { id, fetched_at: FETCHED, origin: 'snapshot', content: p.content ?? '', ...p };
}

export const MOCK_NEWS: MockNews[] = [
  mk('0b7c2a54-1f0e-4c5e-9a51-6a1d2f3e4b01', {
    title: 'Банк России сохранил ключевую ставку на уровне 14,00% годовых',
    summary:
      'Совет директоров Банка России принял решение сохранить ключевую ставку. Регулятор указал на повышенные инфляционные ожидания и рост устойчивых компонентов инфляции. [Учебная мок-новость]',
    url: 'https://example.com/mock/cbr-key-rate-hold',
    source_name: 'Банк России [мок]',
    published_at: ts('2026-10-23T13:30:00'),
    event: {
      event_type: 'key_rate',
      event_label: 'Ключевая ставка и ДКП',
      sectors: ['finance'],
      sector_labels: ['Финансы и холдинги'],
      direction: 'hold',
      regions: [],
    },
    channels: { cost_of_debt: 1.0, liquidity_yield: 0.8, construction_cycle: 0.4, consumer_demand: 0.3 },
    importance: 0.85,
    business: true,
    bankChunks: ['alfa-key-rate-2026-09-11#p1-2', 'alfa-key-rate-2026-09-11#p1-8', 'alfa-bond-brief-2026-09-14#p1-1'],
  }),
  mk('1a2b3c4d-0002-4c5e-9a51-6a1d2f3e4b02', {
    title: 'Доходности ОФЗ на дальнем участке кривой выросли после решения по ставке',
    summary:
      'Инвесторы закладывают более длительный период высоких ставок; стоимость рыночных заимствований для корпоративных эмитентов остаётся повышенной. [Учебная мок-новость]',
    url: 'https://example.com/mock/ofz-yields',
    source_name: 'Интерфакс [мок]',
    published_at: ts('2026-10-23T18:05:00'),
    event: {
      event_type: 'credit_market',
      event_label: 'Кредитный и долговой рынок',
      sectors: ['finance'],
      sector_labels: ['Финансы и холдинги'],
      direction: 'up',
      regions: [],
    },
    channels: { cost_of_debt: 0.9, liquidity_yield: 0.5 },
    importance: 0.45,
    business: true,
    bankChunks: ['alfa-bond-brief-2026-09-14#p1-1'],
  }),
  mk('1a2b3c4d-0003-4c5e-9a51-6a1d2f3e4b03', {
    title: 'Биржевые цены на дизельное топливо и бензин продолжили рост',
    summary:
      'Стоимость топлива на бирже обновила локальные максимумы; участники рынка обсуждают меры по стабилизации внутреннего рынка нефтепродуктов. [Учебная мок-новость]',
    url: 'https://example.com/mock/fuel-prices',
    source_name: 'Коммерсантъ [мок]',
    published_at: ts('2026-10-22T10:15:00'),
    event: {
      event_type: 'fuel_energy',
      event_label: 'Топливо и энергоносители',
      sectors: ['fuel_energy', 'transport'],
      sector_labels: ['Топливо и энергетика', 'Транспорт и логистика'],
      direction: 'up',
      regions: [],
    },
    channels: { fuel_costs: 1.0, foreign_trade: 0.2 },
    importance: 0.45,
    business: true,
    bankChunks: ['alfa-inflation-2026-09-02#p1-1'],
  }),
  mk('1a2b3c4d-0004-4c5e-9a51-6a1d2f3e4b04', {
    title: 'Рост оборота розничной торговли замедляется: покупатели сокращают крупные покупки',
    summary:
      'Оперативные данные указывают на охлаждение потребительского спроса в непродовольственном сегменте, особенно в продажах автомобилей и одежды. [Учебная мок-новость]',
    url: 'https://example.com/mock/retail-slowdown',
    source_name: 'РБК [мок]',
    published_at: ts('2026-10-21T09:40:00'),
    event: {
      event_type: 'consumer_demand',
      event_label: 'Потребительский спрос и розница',
      sectors: ['retail', 'consumer_goods'],
      sector_labels: ['Розничная торговля', 'Потребительские товары'],
      direction: 'down',
      regions: [],
    },
    channels: { consumer_demand: 1.0 },
    importance: 0.45,
    business: true,
    bankChunks: ['alfa-consumption-2026-08-05#p1-3', 'alfa-macrostat-7m26-2026-09-07#p1-2'],
  }),
  mk('1a2b3c4d-0005-4c5e-9a51-6a1d2f3e4b05', {
    title: 'Застройщики сокращают запуск новых проектов на фоне дорогой ипотеки',
    summary:
      'Девелоперы переносят старт продаж части проектов; объём ввода жилья в ряде регионов снижается. [Учебная мок-новость]',
    url: 'https://example.com/mock/construction-starts',
    source_name: 'Ведомости [мок]',
    published_at: ts('2026-10-20T12:00:00'),
    event: {
      event_type: 'real_estate',
      event_label: 'Строительство и недвижимость',
      sectors: ['construction', 'real_estate'],
      sector_labels: ['Строительство', 'Недвижимость'],
      direction: 'down',
      regions: ['Москва', 'Вологодская область'],
    },
    channels: { construction_cycle: 1.0, cost_of_debt: 0.3 },
    importance: 0.3,
    business: true,
    bankChunks: [],
  }),
  mk('1a2b3c4d-0006-4c5e-9a51-6a1d2f3e4b06', {
    title: 'Изменён порядок таможенного оформления импортной рыбной продукции',
    summary:
      'Новые требования к документам при ввозе охлаждённой и мороженой рыбы вступают в силу с 1 декабря; импортёры ожидают удлинения сроков оформления. [Учебная мок-новость]',
    url: 'https://example.com/mock/customs-fish',
    source_name: 'ТАСС [мок]',
    published_at: ts('2026-10-19T16:20:00'),
    event: {
      event_type: 'trade_sanctions',
      event_label: 'Внешняя торговля и санкции',
      sectors: ['agri_food', 'wholesale'],
      sector_labels: ['Агро и продукты питания', 'Оптовая торговля'],
      direction: null,
      regions: ['Санкт-Петербург'],
    },
    channels: { foreign_trade: 1.0, agri_prices: 0.4 },
    importance: 0.4,
    business: true,
    bankChunks: [],
  }),
  mk('1a2b3c4d-0007-4c5e-9a51-6a1d2f3e4b07', {
    title: 'Дефицит кадров: зарплаты в рознице и общепите растут быстрее инфляции',
    summary:
      'Работодатели в потребительском секторе продолжают повышать оплату труда, чтобы удержать персонал. [Учебная мок-новость]',
    url: 'https://example.com/mock/labor-market',
    source_name: 'Известия [мок]',
    published_at: ts('2026-10-18T08:30:00'),
    event: {
      event_type: 'labor_market',
      event_label: 'Рынок труда',
      sectors: ['retail', 'hospitality'],
      sector_labels: ['Розничная торговля', 'Общепит, гостиницы и досуг'],
      direction: 'up',
      regions: ['Москва'],
    },
    channels: { payroll: 1.0, consumer_demand: 0.3 },
    importance: 0.5,
    business: true,
    bankChunks: ['alfa-macrostat-7m26-2026-09-07#p1-1'],
  }),
  mk('1a2b3c4d-0008-4c5e-9a51-6a1d2f3e4b08', {
    title: 'Цены на стальной прокат на внутреннем рынке скорректировались',
    summary: 'Металлотрейдеры фиксируют снижение цен на арматуру и листовой прокат. [Учебная мок-новость]',
    url: 'https://example.com/mock/steel',
    source_name: 'Металлоснабжение и сбыт [мок]',
    published_at: ts('2026-10-16T11:00:00'),
    event: {
      event_type: 'metals',
      event_label: 'Металлы и сырьё',
      sectors: ['metals_mining', 'construction'],
      sector_labels: ['Металлы и добыча', 'Строительство'],
      direction: 'down',
      regions: [],
    },
    channels: { metals_prices: 1.0, foreign_trade: 0.2 },
    importance: 0.25,
    business: true,
    bankChunks: ['alfa-russian-steel-2021-04-15#p1-1'],
  }),
  mk('1a2b3c4d-0009-4c5e-9a51-6a1d2f3e4b09', {
    title: 'Цены на золото колеблются вблизи исторических максимумов',
    summary: 'Спрос центральных банков поддерживает котировки драгметаллов. [Учебная мок-новость]',
    url: 'https://example.com/mock/gold',
    source_name: 'Прайм [мок]',
    published_at: ts('2026-10-17T14:00:00'),
    event: {
      event_type: 'gold',
      event_label: 'Золото и драгметаллы',
      sectors: ['finance'],
      sector_labels: ['Финансы и холдинги'],
      direction: null,
      regions: [],
    },
    channels: { financial_markets: 0.4 },
    importance: 0.15,
    business: true,
    bankChunks: [],
  }),
  mk('1a2b3c4d-0010-4c5e-9a51-6a1d2f3e4b10', {
    title: 'Сборная одержала победу в товарищеском матче',
    summary: 'Спортивная новость. [Учебная мок-новость]',
    url: 'https://example.com/mock/sport',
    source_name: 'Спорт-Экспресс [мок]',
    published_at: ts('2026-10-22T21:00:00'),
    event: {
      event_type: 'other',
      event_label: 'Не бизнес-событие',
      sectors: [],
      sector_labels: [],
      direction: null,
      regions: [],
    },
    channels: {},
    importance: 0,
    business: false,
    bankChunks: [],
  }),
  mk('1a2b3c4d-0011-4c5e-9a51-6a1d2f3e4b11', {
    title: 'Состоялась премьера нового сериала стримингового сервиса',
    summary: 'Новость из раздела культуры. [Учебная мок-новость]',
    url: 'https://example.com/mock/culture',
    source_name: 'Афиша [мок]',
    published_at: ts('2026-10-21T19:00:00'),
    event: {
      event_type: 'other',
      event_label: 'Не бизнес-событие',
      sectors: [],
      sector_labels: [],
      direction: null,
      regions: [],
    },
    channels: {},
    importance: 0,
    business: false,
    bankChunks: [],
  }),
];

/** Дубликаты (те же события в других источниках). */
export const MOCK_DUPLICATES: Record<string, Array<{ news_id: string; title: string; source_name: string; url: string }>> = {
  '0b7c2a54-1f0e-4c5e-9a51-6a1d2f3e4b01': [
    {
      news_id: '9f000000-0000-4000-8000-000000000001',
      title: 'ЦБ оставил ключевую ставку без изменений',
      source_name: 'РБК [мок]',
      url: 'https://example.com/mock/rbc-key-rate',
    },
    {
      news_id: '9f000000-0000-4000-8000-000000000002',
      title: 'Регулятор взял паузу в снижении ставки',
      source_name: 'Ведомости [мок]',
      url: 'https://example.com/mock/vedomosti-key-rate',
    },
  ],
  '1a2b3c4d-0003-4c5e-9a51-6a1d2f3e4b03': [
    {
      news_id: '9f000000-0000-4000-8000-000000000003',
      title: 'Дизельное топливо на бирже подорожало',
      source_name: 'Интерфакс [мок]',
      url: 'https://example.com/mock/ifx-diesel',
    },
  ],
};

export interface MockChunk {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  page: number;
  url: string;
  published_at: string;
  text: string;
  /** Дословная выдержка из text для блока «цитата» */
  quote: string;
  /** Пересказ (в моках — краткое изложение фрагмента) */
  retelling: string;
}

// Тексты фрагментов — выдержки из data/bank_corpus/corpus.json (OCR, обрезаны по границам предложений).
// Поле retelling — пересказ, написанный для мока.
export const MOCK_CHUNKS: Record<string, MockChunk> = {
  'alfa-key-rate-2026-09-11#p1-2': {
    chunk_id: 'alfa-key-rate-2026-09-11#p1-2',
    doc_id: 'alfa-key-rate-2026-09-11',
    doc_title: 'Ключевая ставка ЦБ РФ: ставка без изменения на 14,0%, риторика стала жестче',
    page: 1,
    url: 'https://drive.google.com/file/d/1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-/view',
    published_at: '2026-09-11',
    text: 'Однако на пресс-конференции глава ЦБ РФ пояснила, что совет директоров предметно обсуждал только вариант паузы, а вариант снижения ставки не рассматривался; кроме того, пресс-релиз содержит несколько важных корректировок в коммуникации, также свидетельствующих об ужесточении позиции. ЦБ РФ отметил ускорение роста цен в устойчивых компонентах до 5-6%.',
    quote:
      'пресс-релиз содержит несколько важных корректировок в коммуникации, также свидетельствующих об ужесточении позиции',
    retelling: 'Аналитики банка расценили коммуникацию ЦБ как более жёсткую: вариант снижения ставки не рассматривался.',
  },
  'alfa-key-rate-2026-09-11#p1-8': {
    chunk_id: 'alfa-key-rate-2026-09-11#p1-8',
    doc_id: 'alfa-key-rate-2026-09-11',
    doc_title: 'Ключевая ставка ЦБ РФ: ставка без изменения на 14,0%, риторика стала жестче',
    page: 1,
    url: 'https://drive.google.com/file/d/1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-/view',
    published_at: '2026-09-11',
    text: 'Первый это динамика корпоративного кредитования, которое сейчас, напомним, идет по траектории более быстрого роста по сравнению с прогнозами ЦБ РФ (см нашу публикацию «Прогноз решения по ставке 11 сентября: Ждем паузу на 14,0% в сентябре, неопределенность смещается на 4К26» от 4 сентября 2026 г.). Вторым фактором остаются вводные по бюджету в конце этого месяца Минфин должен представить параметры нового трехлетнего бюджета.',
    quote:
      'динамика корпоративного кредитования, которое сейчас, напомним, идет по траектории более быстрого роста по сравнению с прогнозами ЦБ РФ',
    retelling:
      'Банк выделяет корпоративное кредитование и бюджет как два индикатора, по которым ЦБ будет оценивать спрос.',
  },
  'alfa-bond-brief-2026-09-14#p1-1': {
    chunk_id: 'alfa-bond-brief-2026-09-14#p1-1',
    doc_id: 'alfa-bond-brief-2026-09-14',
    doc_title: 'Бонд Бриф: итоги недели',
    page: 1,
    url: 'https://drive.google.com/file/d/1bPzix_332N2CyMY0tqCHuYtGsfJWnFGv/view',
    published_at: '2026-09-14',
    text: 'В пятницу 11 сентября ЦБ ожидаемо сохранил ключевую ставку на уровне 14,0%, однако долговые инвесторы остались разочарованы тем, что регулятор не рассматривал опцию снижения ставки. После заседания на дальнем участке кривой ОФЗ доходность выросла, на пике подойдя к уровню 16,3%.',
    quote: 'После заседания на дальнем участке кривой ОФЗ доходность выросла, на пике подойдя к уровню 16,3%.',
    retelling: 'После паузы ЦБ доходности длинных ОФЗ выросли — рыночный долг остаётся дорогим.',
  },
  'alfa-inflation-2026-09-02#p1-1': {
    chunk_id: 'alfa-inflation-2026-09-02#p1-1',
    doc_id: 'alfa-inflation-2026-09-02',
    doc_title: 'Инфляция 25–31 августа: основные выводы',
    page: 1,
    url: 'https://drive.google.com/file/d/19iW3Ph8_wO0HHQY7Ik4lTfC3jRc9gjWV/view',
    published_at: '2026-09-02',
    text: 'За прошедшую неделю (25.08-31.08) Росстат зафиксировал дефляцию на 0,01% н/н после инфляции на 0,01% н/н на предыдущей неделе 18.08-24.08. На 31 августа снижение цен с начала месяца составило 0,08%, с начала года рост цен составил 4,67%. годовом выражении инфляция выросла до 6,32%. • Рост цен на остался умеренно высоким - 0,91% н/н после роста на 0,89% н/н неделей ранее. Цены на дизель остались почти без изменений.',
    quote: 'Цены на дизель остались почти без изменений.',
    retelling: 'В начале сентября банк фиксировал стабильные цены на дизель на фоне общей дефляции.',
  },
  'alfa-consumption-2026-08-05#p1-3': {
    chunk_id: 'alfa-consumption-2026-08-05#p1-3',
    doc_id: 'alfa-consumption-2026-08-05',
    doc_title: 'Потребление на пике',
    page: 1,
    url: 'https://drive.google.com/file/d/1riR1lhsb6EY1MwGMxdBlS_tI5ed9mIiz/view',
    published_at: '2026-08-05',
    text: 'В целом мы считаем, что сильный рост оборота розничной торговли за 1П26 на 5,4% г/г был реализован «взаймы» у 2П26, и ожидаем замедления роста этого показателя до 1,5% г/г на 2П26, включая нулевой рост в 4К26.',
    quote: 'ожидаем замедления роста этого показателя до 1,5% г/г на 2П26, включая нулевой рост в 4К26',
    retelling: 'Банк ожидает замедления роста розничного оборота во втором полугодии вплоть до нулевого в 4К26.',
  },
  'alfa-macrostat-7m26-2026-09-07#p1-2': {
    chunk_id: 'alfa-macrostat-7m26-2026-09-07#p1-2',
    doc_id: 'alfa-macrostat-7m26-2026-09-07',
    doc_title: 'Макростатистика 7М26: данные по рынку труда не подтверждают охлаждения экономики',
    page: 1,
    url: 'https://drive.google.com/file/d/1HZDq3WGRFdzgm1TZ5hWL23Q3I9c2Eq64/view',
    published_at: '2026-09-07',
    text: 'Динамика спроса в июле складывалась в рамках наших ожиданий, темпы роста оборота розничной торговли замедлились до 5,3% г/г после периода быстрого роста на 7,2% г/г в 2К26. Основной причиной мы считаем замедление роста потребления в сегменте непродовольственных товаров, в частности в сегменте покупок автомобилей.',
    quote: 'Основной причиной мы считаем замедление роста потребления в сегменте непродовольственных товаров',
    retelling: 'Замедление розницы банк связывает прежде всего с непродовольственным сегментом.',
  },
  'alfa-macrostat-7m26-2026-09-07#p1-1': {
    chunk_id: 'alfa-macrostat-7m26-2026-09-07#p1-1',
    doc_id: 'alfa-macrostat-7m26-2026-09-07',
    doc_title: 'Макростатистика 7М26: данные по рынку труда не подтверждают охлаждения экономики',
    page: 1,
    url: 'https://drive.google.com/file/d/1HZDq3WGRFdzgm1TZ5hWL23Q3I9c2Eq64/view',
    published_at: '2026-09-07',
    text: 'Ключевым вопросом текущих месяцев является скорость охлаждения рынка труда, этот фактор выглядит основным аргументом в пользу возможного продолжения цикла снижения ставки. Доступные оперативные данные и показатели рынка труда летом 2026 г. оставались достаточно сильными.',
    quote: 'Доступные оперативные данные и показатели рынка труда летом 2026 г. оставались достаточно сильными.',
    retelling: 'По оценке банка, рынок труда летом оставался сильным — давление на зарплаты сохраняется.',
  },
  'alfa-russian-steel-2021-04-15#p1-1': {
    chunk_id: 'alfa-russian-steel-2021-04-15#p1-1',
    doc_id: 'alfa-russian-steel-2021-04-15',
    doc_title: 'Commodities performance: Российская сталь — ралли цен продолжается (прогноз за 1К21)',
    page: 1,
    url: 'https://drive.google.com/file/d/1yLCBrIoyIsubLTEBvBHh6io48ysnW-wn/view',
    published_at: '2021-04-15',
    text: 'Поскольку Европа не может удовлетворить отложенный спрос в связи с медленным перезапуском остановленных мощностей, а спрос в США растет после нового пакета стимулов, мы ожидаем, что рентабельность крупнейших российских производителей стали улучшится за счет экспортных продаж и благодаря их эффективной сырьевой интеграции.',
    quote: 'мы ожидаем, что рентабельность крупнейших российских производителей стали улучшится за счет экспортных продаж',
    retelling: 'Материал 2021 года: банк ожидал роста рентабельности сталепроизводителей за счёт экспорта.',
  },
};
